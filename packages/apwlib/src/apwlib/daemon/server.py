"""The daemon: owns a managed browser and bridges CLI clients to the extension.

Layout::

    unix socket (clients) ──▶ ExtensionBridge ──▶ py_chauffeur channel (in-browser bridge)

chauffeur installs a ``py_chauffeur`` channel in the extension's service worker, so the
daemon drives the in-browser bridge's ``request`` handler directly and the bridge pushes
pairing state back through a ``@command``. Requests are serialized (the bridge handles one
native round-trip at a time).
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import os
import shutil
import signal
from pathlib import Path

from chauffeur import Browser as ManagedBrowser
from chauffeur import ExtensionNotFoundError, LaunchSpec

from apwlib.browsers import Browser
from apwlib.daemon.extension import extension_spec
from apwlib.errors import ApwError
from apwlib.paths import (
    APPLE_NATIVE_MANIFEST,
    LOCK_PATH,
    SOCKET_PATH,
    ensure_data_dir,
)
from apwlib.protocol import WIRE_NO_BRIDGE, Status

REQUEST_TIMEOUT = 30.0


class ExtensionBridge:
    """Talks to the in-browser bridge over chauffeur's extension worker channel.

    Replaces the old hand-rolled WebSocket: chauffeur installs ``py_chauffeur`` in the
    extension's service worker, so ``request()`` invokes the bridge's ``request`` handler
    and ``pairing()`` pulls live pairing state from its ``status`` handler. Pulling (not
    caching a push) is race-free: a poll reads the current truth, and a read issued while
    the worker is mid-handshake queues behind the crypto and returns the settled state.
    Requests are serialized because the bridge tracks a single native round-trip at a time.
    """

    def __init__(self, browser: ManagedBrowser) -> None:
        self._browser = browser
        self.extension_id: str | None = None  # set once the extension is loaded
        self._lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        """Whether the extension's service worker has attached its py_chauffeur channel."""
        return self.extension_id is not None and self._browser.extension_ready(self.extension_id)

    async def pairing(self) -> dict:
        """Live pairing state pulled from the worker: ``{"paired": bool, "state": str|None}``.

        Not serialized against :meth:`request`: the worker's ``status`` handler only reads
        ``g_theState`` (no native round-trip), so a status poll can run alongside an
        in-flight request. Any failure reads as unpaired.
        """
        extension_id = self.extension_id
        if extension_id is None or not self._browser.extension_ready(extension_id):
            return {"paired": False, "state": None}
        try:
            channel = self._browser.extension(extension_id)
            result = await channel.call("status", timeout=REQUEST_TIMEOUT)
            return {"paired": bool(result.get("paired")), "state": result.get("state")}
        except LookupError:
            return {"paired": False, "state": None}
        except Exception:  # noqa: BLE001 - a status poll must never propagate
            return {"paired": False, "state": None}

    async def request(self, message: dict) -> dict:
        async with self._lock:
            extension_id = self.extension_id
            if extension_id is None or not self._browser.extension_ready(extension_id):
                return {"status": Status.INVALID_SESSION, "error": WIRE_NO_BRIDGE}
            try:
                channel = self._browser.extension(extension_id)
                return await channel.call("request", message, timeout=REQUEST_TIMEOUT)
            except LookupError:
                # The worker was evicted between the readiness check and the call.
                return {"status": Status.INVALID_SESSION, "error": WIRE_NO_BRIDGE}
            except Exception as exc:  # noqa: BLE001 - a daemon request must never propagate
                # JS error, dropped worker, or transport failure -> a response, not a crash.
                return {"status": Status.SERVER_ERROR, "error": str(exc) or "request failed"}


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    bridge: ExtensionBridge,
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
            pairing = await bridge.pairing()  # pulled live from the worker
            response: dict = {
                "running": True,
                "bridge": bridge.ready,
                "paired": pairing["paired"],
                "pairing_state": pairing["state"],
                "browser": browser.name,
                "browser_pid": browser_pid,
            }
        elif op == "stop":
            response = {"stopping": True}
            if not stop.done():
                stop.set_result(None)
        else:
            response = await bridge.request(message)
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

    # Everything past the lock is guarded: a failure while launching the browser or
    # loading the extension must still release the lock, or we'd pile a browser up on
    # every retry. The browser itself is context-managed: chauffeur launches it
    # (headless, minimal footprint), builds the patched extension beside the profile,
    # loads it over CDP, installs the worker channel, and terminates it on exit —
    # including a failed start.
    unix_server: asyncio.Server | None = None
    watcher: asyncio.Task[None] | None = None
    try:
        spec = LaunchSpec(
            profile=_prepare_profile(browser),
            browser=browser.binary,
            headless=True,
            extensions=(extension_spec(),),
        )
        managed = ManagedBrowser(spec)
        bridge = ExtensionBridge(managed)

        async with managed:
            if not managed.extension_ids:
                raise ApwError(
                    Status.GENERIC_ERROR, "the iCloud Passwords extension failed to load"
                )
            bridge.extension_id = managed.extension_ids[0]
            browser_pid = managed.handle.proc.pid if managed.handle else 0

            stop = asyncio.get_running_loop().create_future()
            for sig in (signal.SIGINT, signal.SIGTERM):
                with contextlib.suppress(NotImplementedError):
                    asyncio.get_running_loop().add_signal_handler(
                        sig, lambda: stop.done() or stop.set_result(None)
                    )
            # Worker liveness is chauffeur's job: the spec's keep_alive (see
            # extension.py) pokes the worker so the SRP session never goes dormant.
            watcher = asyncio.create_task(_watch_browser(managed, stop))

            if SOCKET_PATH.exists():
                SOCKET_PATH.unlink()
            unix_server = await asyncio.start_unix_server(
                lambda r, w: _handle_client(r, w, bridge, stop, browser, browser_pid),
                path=str(SOCKET_PATH),
            )
            SOCKET_PATH.chmod(0o600)

            print(f"apwlib daemon ready ({browser.name}); socket at {SOCKET_PATH}", flush=True)
            try:
                await stop
            finally:
                # Stop accepting clients BEFORE the browser teardown that runs on
                # leaving the async-with (it can take seconds). Shutdown order the
                # client relies on: socket first, browser next, lock last.
                unix_server.close()
                with contextlib.suppress(FileNotFoundError):
                    SOCKET_PATH.unlink()
    except ExtensionNotFoundError as exc:
        # Only the store download can raise this here: a first-ever fetch failed
        # with no cache to fall back on. Say so in apwlib's error vocabulary.
        raise ApwError(
            Status.GENERIC_ERROR,
            f"could not download the iCloud Passwords extension from the Chrome Web Store: {exc}",
        ) from exc
    finally:
        if watcher is not None:
            watcher.cancel()
        if unix_server is not None:
            unix_server.close()
        with contextlib.suppress(FileNotFoundError):
            SOCKET_PATH.unlink()
        os.close(lock_fd)
