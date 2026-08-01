"""The daemon: owns a managed browser and bridges CLI clients to the extension.

Layout::

    unix socket (clients) ──▶ ExtensionSession ──▶ WebSocket (in-browser bridge)

One bridge connects at a time; requests are serialized and matched by a generated id.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import os
import secrets
import shutil
import signal
import socket as socketlib
from pathlib import Path

import websockets
from chauffeur import Browser as ManagedBrowser
from chauffeur import LaunchSpec

from apwlib.browsers import Browser
from apwlib.daemon.extension import extension_spec
from apwlib.paths import (
    APPLE_NATIVE_MANIFEST,
    LOCK_PATH,
    SOCKET_PATH,
    ensure_data_dir,
)
from apwlib.protocol import WIRE_NO_BRIDGE, Status

REQUEST_TIMEOUT = 30.0


def _free_port() -> int:
    with socketlib.socket(socketlib.AF_INET, socketlib.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ExtensionSession:
    """Tracks the single bridge WebSocket and correlates requests with responses."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._ws: websockets.ServerConnection | None = None
        self._pending: dict[str, asyncio.Future[dict]] = {}
        self._lock = asyncio.Lock()
        self._paired = False  # last pairing state reported by the bridge
        self._pairing_state: str | None = None  # raw handshake state (NotInSession/MSG1Set/…)

    @property
    def ready(self) -> bool:
        return self._ws is not None

    @property
    def paired(self) -> bool:
        return self._ws is not None and self._paired

    @property
    def pairing_state(self) -> str | None:
        return self._pairing_state if self._ws is not None else None

    async def serve(self, ws: websockets.ServerConnection) -> None:
        """Handle one bridge connection for its lifetime."""
        try:
            hello = json.loads(await ws.recv())
        except (websockets.ConnectionClosed, ValueError):
            return
        if hello.get("token") != self._token:
            await ws.close(code=4003, reason="unauthorized")
            return
        if self._ws is not None:
            await ws.close(code=4001, reason="already connected")
            return
        self._ws = ws
        try:
            async for raw in ws:
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                if "paired" in message:  # bridge reporting its pairing state
                    self._paired = bool(message["paired"])
                    self._pairing_state = message.get("state")
                    continue
                future = self._pending.pop(message.get("id"), None)
                if future and not future.done():
                    future.set_result(message)
        except websockets.ConnectionClosed:
            pass
        finally:
            self._ws = None
            self._paired = False
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("Extension disconnected"))
            self._pending.clear()

    async def request(self, message: dict) -> dict:
        async with self._lock:
            if self._ws is None:
                return {
                    "id": "",
                    "status": Status.INVALID_SESSION,
                    "error": WIRE_NO_BRIDGE,
                }
            request_id = secrets.token_hex(8)
            loop = asyncio.get_running_loop()
            future: asyncio.Future[dict] = loop.create_future()
            self._pending[request_id] = future
            await self._ws.send(json.dumps({**message, "id": request_id}))
            try:
                return await asyncio.wait_for(future, REQUEST_TIMEOUT)
            except (TimeoutError, ConnectionError) as exc:
                self._pending.pop(request_id, None)
                return {
                    "id": request_id,
                    "status": Status.SERVER_ERROR,
                    "error": str(exc) or "timed out",
                }


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    session: ExtensionSession,
    stop: asyncio.Future[None],
    browser: Browser,
    browser_pid: int,
) -> None:
    try:
        line = await asyncio.wait_for(reader.readline(), REQUEST_TIMEOUT)
        if not line:
            return
        message = json.loads(line)
        op = message.get("op")
        if op == "status":
            response: dict = {
                "running": True,
                "bridge": session.ready,
                "paired": session.paired,
                "pairing_state": session.pairing_state,
                "browser": browser.name,
                "browser_pid": browser_pid,
            }
        elif op == "stop":
            response = {"stopping": True}
            if not stop.done():
                stop.set_result(None)
        else:
            response = await session.request(message)
        writer.write((json.dumps(response) + "\n").encode())
        await writer.drain()
    except (ValueError, TimeoutError):
        writer.write(
            (
                json.dumps({"id": "", "status": Status.SERVER_ERROR, "error": "bad request"}) + "\n"
            ).encode()
        )
        with contextlib.suppress(Exception):
            await writer.drain()
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


def _prepare_profile(browser: Browser) -> Path:
    profile = browser.profile
    if profile.exists():
        shutil.rmtree(profile)
    hosts = profile / "NativeMessagingHosts"
    hosts.mkdir(parents=True)
    shutil.copyfile(APPLE_NATIVE_MANIFEST, hosts / "com.apple.passwordmanager.json")
    return profile


def _acquire_singleton_lock() -> int | None:
    """Take the exclusive daemon lock, or return None if another daemon holds it.

    The fd is kept open for the process lifetime; the OS releases the lock on exit (even
    on crash), so a stale lock never blocks a restart.
    """
    fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


async def _watch_browser(managed: ManagedBrowser, stop: asyncio.Future[None]) -> None:
    """Trigger shutdown if the managed browser exits, so the lock frees and cleanup runs.

    ``serve()`` returns when the DevTools connection drops (the browser died) or its
    primary target closes — either way the daemon is useless without its browser.
    """
    with contextlib.suppress(Exception):
        await managed.serve()
    if not stop.done():
        stop.set_result(None)


async def run(browser: Browser) -> None:
    """Run the daemon until interrupted. No-op if another daemon already holds the lock."""
    ensure_data_dir()
    lock_fd = _acquire_singleton_lock()
    if lock_fd is None:
        print("apwlib daemon already running; exiting", flush=True)
        return

    token = secrets.token_hex(16)
    session = ExtensionSession(token)

    ws_port = _free_port()
    ws_server = await websockets.serve(session.serve, "127.0.0.1", ws_port)

    # Everything past the lock is guarded: a failure while launching the browser or
    # loading the extension must still terminate the browser and release the lock, or
    # we'd orphan a browser and pile more up on every retry.
    managed: ManagedBrowser | None = None
    unix_server: asyncio.Server | None = None
    watcher: asyncio.Task[None] | None = None
    try:
        # chauffeur launches the browser (headless, minimal footprint), builds the
        # patched extension beside the profile, and loads it over CDP.
        spec = LaunchSpec(
            profile=_prepare_profile(browser),
            browser=browser.binary,
            headless=True,
            extensions=(extension_spec(ws_port, token),),
        )
        managed = await ManagedBrowser(spec).start()
        browser_pid = managed.handle.proc.pid if managed.handle else 0

        stop = asyncio.get_running_loop().create_future()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                asyncio.get_running_loop().add_signal_handler(
                    sig, lambda: stop.done() or stop.set_result(None)
                )
        watcher = asyncio.create_task(_watch_browser(managed, stop))

        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
        unix_server = await asyncio.start_unix_server(
            lambda r, w: _handle_client(r, w, session, stop, browser, browser_pid),
            path=str(SOCKET_PATH),
        )
        SOCKET_PATH.chmod(0o600)

        print(f"apwlib daemon ready ({browser.name}); socket at {SOCKET_PATH}", flush=True)
        await stop
    finally:
        if watcher is not None:
            watcher.cancel()
        if unix_server is not None:
            unix_server.close()
        ws_server.close()
        if managed is not None:
            with contextlib.suppress(Exception):
                await managed.aclose()
        with contextlib.suppress(FileNotFoundError):
            SOCKET_PATH.unlink()
        os.close(lock_fd)
