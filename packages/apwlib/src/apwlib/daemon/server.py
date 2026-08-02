"""The daemon: a chauffeur-managed headless browser hosting the iCloud Passwords
extension, exposed to CLI clients over a unix socket.

Layout::

    unix socket (clients) ──▶ ExtensionBridge ──▶ py_chauffeur channel (in-browser bridge)

chauffeur does the heavy lifting: it launches the browser, builds and loads the
patched extension, installs the ``py_chauffeur`` channel in its service worker,
and keeps the worker awake. The daemon just forwards each client request to the
in-browser bridge's ``request`` handler and answers ``status`` polls from its
``status`` handler.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import os
import shutil
import signal
import time
from pathlib import Path

from chauffeur import Browser, ExtensionNotFoundError, JSError, LaunchSpec, wipe_profile

from apwlib.browsers import BrowserInfo, profile_for
from apwlib.daemon.extension import extension_spec
from apwlib.errors import ApwError
from apwlib.paths import APPLE_NATIVE_MANIFEST, LOCK_PATH, SOCKET_PATH, ensure_data_dir
from apwlib.protocol import WIRE_NO_BRIDGE, Command, Status

REQUEST_TIMEOUT = 30.0
CHALLENGE_TIMEOUT = 10.0  # challenge -> MSG1Set (the native round trip the PIN must wait for)
PAIR_TIMEOUT = 20.0  # SRP round trip after the PIN is submitted
_PAIR_POLL = 0.1


class ExtensionBridge:
    """The ``py_chauffeur`` channel into the extension's service worker.

    ``request()`` invokes the in-browser bridge's ``request`` handler and
    ``pairing()`` pulls live pairing state from its ``status`` handler. Requests
    are serialized because the bridge tracks a single native round-trip at a time.
    """

    def __init__(self, browser: Browser, extension_id: str) -> None:
        self._browser = browser
        self._extension_id = extension_id
        self._lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        """Whether the extension's service worker has attached its py_chauffeur channel."""
        return self._browser.extension_ready(self._extension_id)

    async def pairing(self) -> dict:
        """Live pairing state pulled from the worker: ``{"paired": bool, "state": str|None}``.

        Reads as unpaired while the worker is still booting.
        """
        if not self.ready:
            return {"paired": False, "state": None}
        try:
            result = await self._browser.extension(self._extension_id).call("status", timeout=REQUEST_TIMEOUT)
        except (JSError, LookupError):
            # ready flips true when chauffeur installs the channel, a beat before the
            # appended bridge registers its handlers (JSError: no such handler) — and a
            # respawning worker can detach between the check and the call (LookupError).
            return {"paired": False, "state": None}
        return {"paired": bool(result.get("paired")), "state": result.get("state")}

    async def request(self, message: dict) -> dict:
        async with self._lock:
            if not self.ready:
                return {"status": Status.INVALID_SESSION, "error": WIRE_NO_BRIDGE}
            try:
                return await self._browser.extension(self._extension_id).call("request", message, timeout=REQUEST_TIMEOUT)
            except JSError as exc:  # handler not yet registered (worker still booting)
                return {"status": Status.INVALID_SESSION, "error": str(exc)}
            except LookupError:  # worker detached between the ready check and the call
                return {"status": Status.INVALID_SESSION, "error": WIRE_NO_BRIDGE}

    # -- pairing ---------------------------------------------------------------
    # The daemon owns the waits around the handshake: it watches the worker's state
    # directly, so clients get one blocking op per step instead of polling `status`
    # over the socket and knowing the state machine's vocabulary.

    async def pair_challenge(self, timeout: float = CHALLENGE_TIMEOUT) -> dict:  # noqa: ASYNC109 - a poll deadline, not a cancellation
        """Start a pairing handshake and wait until it is ready for the PIN.

        ``ChallengePIN`` kicks off an async native round trip; a PIN submitted before it
        settles at ``MSG1Set`` wedges the handshake (it never completes and never
        collapses). So this replies only once the state is ``MSG1Set`` — or with
        ``ready: False`` on timeout, and the caller proceeds anyway so a divergent
        state machine can't hang pairing here.
        """
        response = await self.request({"cmd": int(Command.HANDSHAKE)})
        if "error" in response:
            return response
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (await self.pairing())["state"] == "MSG1Set":
                return {"ready": True}
            await asyncio.sleep(_PAIR_POLL)
        return {"ready": False}

    async def pair_verify(self, pin: str, timeout: float = PAIR_TIMEOUT) -> dict:  # noqa: ASYNC109 - a poll deadline, not a cancellation
        """Submit the PIN and wait for pairing to settle; replies ``{"paired": bool}``.

        Called with a handshake in flight (``pair_challenge`` drove the state to
        ``MSG1Set``), so a return to ``NotInSession`` can only mean the helper rejected
        the PIN — report that at once rather than polling to ``timeout``. A correct PIN
        advances ``MSG1Set`` -> ``SessionKeySet`` without ever passing through
        ``NotInSession``, so this never trips on the success path.
        """
        response = await self.request({"cmd": int(Command.HANDSHAKE), "pin": pin})
        if "error" in response:
            return response
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pairing = await self.pairing()
            if pairing["paired"]:
                return {"paired": True}
            if pairing["state"] == "NotInSession":
                return {"paired": False}  # collapsed back to idle — the PIN was rejected
            await asyncio.sleep(_PAIR_POLL)
        return {"paired": False}


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    bridge: ExtensionBridge,
    stop: asyncio.Event,
    browser: BrowserInfo,
    browser_pid: int,
) -> None:
    try:
        message: object = None
        with contextlib.suppress(TimeoutError, json.JSONDecodeError):
            line = await asyncio.wait_for(reader.readline(), REQUEST_TIMEOUT)
            if not line:
                return
            message = json.loads(line)
        if not isinstance(message, dict):
            # Bad JSON (or a read timeout) still deserves a reply: hanging up here
            # would surface on the client as a decode error, not an ApwError.
            response: dict = {"status": Status.INVALID_PARAM, "error": "malformed request"}
        elif message.get("op") == "status":
            pairing = await bridge.pairing()  # pulled live from the worker
            response = {
                "running": True,
                "bridge": bridge.ready,
                "paired": pairing["paired"],
                "pairing_state": pairing["state"],
                "browser": browser.name,
                "browser_pid": browser_pid,
            }
        elif message.get("op") == "stop":
            response = {"stopping": True}
            stop.set()
        elif message.get("op") == "pair_challenge":
            response = await bridge.pair_challenge()
        elif message.get("op") == "pair_verify":
            response = await bridge.pair_verify(str(message.get("pin", "")))
        else:
            response = await bridge.request(message)
        writer.write((json.dumps(response) + "\n").encode())
        await writer.drain()
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


def _prepare_profile(browser: BrowserInfo) -> Path:
    """Reset the managed profile to a clean slate holding only Apple's manifest.

    ``wipe_profile`` first asks a browser still running on the profile (leaked by a
    killed daemon) to exit, so it can't rewrite state on the way out, and removes
    chauffeur's sidecars too. It runs an event loop of its own for that, so this
    must be called off the daemon's loop (see the ``to_thread`` in :func:`run`).
    """
    profile = profile_for(browser)
    wipe_profile(profile)
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


async def run(browser: BrowserInfo) -> None:
    """Run the daemon until interrupted. No-op if another daemon already holds the lock."""
    ensure_data_dir()
    lock_fd = _acquire_singleton_lock()
    if lock_fd is None:
        print("apwlib daemon already running; exiting", flush=True)
        return

    try:
        # to_thread: _prepare_profile runs its own event loop (closing a leaked
        # browser), which is illegal on the daemon's loop thread.
        spec = LaunchSpec(
            profile=await asyncio.to_thread(_prepare_profile, browser),
            browser=browser.binary,
            headless=True,
            extensions=(extension_spec(),),
        )
        try:
            async with Browser(spec) as managed:
                bridge = ExtensionBridge(managed, managed.extension_ids[0])
                browser_pid = managed.handle.proc.pid if managed.handle else 0

                stop = asyncio.Event()
                for sig in (signal.SIGINT, signal.SIGTERM):
                    with contextlib.suppress(NotImplementedError):
                        asyncio.get_running_loop().add_signal_handler(sig, stop.set)

                SOCKET_PATH.unlink(missing_ok=True)
                unix_server = await asyncio.start_unix_server(
                    lambda r, w: _handle_client(r, w, bridge, stop, browser, browser_pid),
                    path=str(SOCKET_PATH),
                )
                SOCKET_PATH.chmod(0o600)
                print(f"apwlib daemon ready ({browser.name}); socket at {SOCKET_PATH}", flush=True)

                try:
                    await managed.serve(until=stop)  # returns on stop, or if the browser dies
                finally:
                    # Stop accepting clients BEFORE the browser teardown that runs on
                    # leaving the async-with (it can take seconds). Shutdown order the
                    # client relies on: socket first, browser next, lock last.
                    unix_server.close()
                    SOCKET_PATH.unlink(missing_ok=True)
        except ExtensionNotFoundError as exc:
            # Only the store download can raise this here: a first-ever fetch failed
            # with no cache to fall back on. Say so in apwlib's error vocabulary.
            raise ApwError(
                Status.GENERIC_ERROR,
                f"could not download the iCloud Passwords extension from the Chrome Web Store: {exc}",
            ) from exc
    finally:
        os.close(lock_fd)
