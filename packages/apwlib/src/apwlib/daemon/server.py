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
from typing import Protocol

import websockets

from apwlib.browsers import Browser
from apwlib.daemon.cdp import load_unpacked_extension
from apwlib.daemon.extension import build_extension
from apwlib.paths import (
    APPLE_NATIVE_MANIFEST,
    LOCK_PATH,
    SOCKET_PATH,
    ensure_data_dir,
)
from apwlib.protocol import Status

REQUEST_TIMEOUT = 30.0

_BROWSER_FLAGS = [
    "--remote-allow-origins=*",
    "--enable-unsafe-extension-debugging",
    "--headless=new",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
]


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

    @property
    def ready(self) -> bool:
        return self._ws is not None

    @property
    def paired(self) -> bool:
        return self._ws is not None and self._paired

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
                    "error": "no extension connected",
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
) -> None:
    try:
        line = await asyncio.wait_for(reader.readline(), REQUEST_TIMEOUT)
        if not line:
            return
        message = json.loads(line)
        op = message.get("op")
        if op == "status":
            response: dict = {"running": True, "bridge": session.ready, "paired": session.paired}
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


class _Waitable(Protocol):
    async def wait(self) -> int: ...


async def _watch_child(child: _Waitable, stop: asyncio.Future[None]) -> None:
    """Trigger shutdown if the managed browser exits, so the lock frees and cleanup runs."""
    with contextlib.suppress(Exception):
        await child.wait()
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
    # loading the extension must still terminate the child and release the lock, or
    # we'd orphan a browser and pile more up on every retry.
    child: asyncio.subprocess.Process | None = None
    unix_server: asyncio.Server | None = None
    watcher: asyncio.Task[None] | None = None
    try:
        extension_path = build_extension(ws_port, token)
        profile = _prepare_profile(browser)
        devtools_port = _free_port()

        child = await asyncio.create_subprocess_exec(
            str(browser.binary),
            f"--user-data-dir={profile}",
            f"--remote-debugging-port={devtools_port}",
            *_BROWSER_FLAGS,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await load_unpacked_extension(devtools_port, str(extension_path))

        stop = asyncio.get_running_loop().create_future()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                asyncio.get_running_loop().add_signal_handler(
                    sig, lambda: stop.done() or stop.set_result(None)
                )
        watcher = asyncio.create_task(_watch_child(child, stop))

        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
        unix_server = await asyncio.start_unix_server(
            lambda r, w: _handle_client(r, w, session, stop), path=str(SOCKET_PATH)
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
        if child is not None:
            with contextlib.suppress(ProcessLookupError):
                child.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(child.wait(), 5)
        with contextlib.suppress(FileNotFoundError):
            SOCKET_PATH.unlink()
        os.close(lock_fd)
