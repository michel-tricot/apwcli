"""Synchronous facade — the public API. Talks to the daemon's unix socket."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

from apwlib import protocol
from apwlib.errors import (
    ApwError,
    DaemonNotRunningError,
    NotPairedError,
    SessionError,
    error_for,
)
from apwlib.models import OTPEntry, PasswordEntry
from apwlib.paths import LOG_PATH, SOCKET_PATH, ensure_data_dir
from apwlib.protocol import Command, Status

_NO_DAEMON = "daemon not running"
_NO_BRIDGE = "no extension connected"
_UNPAIRED = "unpaired"

_TIMEOUT = 35.0
_START_TIMEOUT = 45.0  # browser launch + extension load + bridge connect
_PAIR_TIMEOUT = 20.0  # SRP round-trip after the PIN is entered
_LOG_MAX_BYTES = 1_000_000  # rotate the daemon log once it grows past ~1 MB


def _rotate_log() -> None:
    """Keep one previous daemon log (``.log`` -> ``.log.1``) when it grows too large."""
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > _LOG_MAX_BYTES:
            LOG_PATH.replace(LOG_PATH.with_name(LOG_PATH.name + ".1"))
    except OSError:
        pass


def _error(response: dict[str, Any]) -> str | None:
    """The error string of a response, or None if it carried data."""
    return None if "data" in response else response.get("error")


class _Daemon:
    """The connection to the background daemon: transport, lifecycle, and pairing.

    Exposed as :attr:`ApplePasswords.daemon`. Callers rarely touch it — the facade
    auto-starts and auto-pairs — but it backs ``apwcli daemon start/stop/status/pair``.
    """

    def __init__(self, socket_path: str, auto_start: bool = True) -> None:
        self._socket_path = socket_path
        self._auto_start = auto_start

    # -- transport -------------------------------------------------------------
    def _send_raw(self, message: dict[str, Any]) -> dict[str, Any]:
        """Send one message. Raises ``DaemonNotRunningError`` if the socket is unreachable."""
        try:
            conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.settimeout(_TIMEOUT)
            conn.connect(self._socket_path)
        except OSError as exc:
            raise DaemonNotRunningError(Status.INVALID_SESSION, _NO_DAEMON) from exc
        try:
            conn.sendall((json.dumps(message) + "\n").encode())
            buffer = b""
            while b"\n" not in buffer:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buffer += chunk
            return json.loads(buffer.split(b"\n", 1)[0])
        finally:
            conn.close()

    def deliver(self, message: dict[str, Any]) -> dict[str, Any]:
        """Deliver a message, recovering from a missing daemon or a booting bridge.

        - no daemon -> auto-start (if enabled) and retry once, else ``DaemonNotRunningError``
        - bridge not connected -> (auto-start) recover via ``start`` and retry once. This
          covers both a bridge still booting and a wedged daemon (alive but bridge dead),
          which ``start`` replaces rather than waiting on forever.

        Returns the raw response; an ``unpaired`` response is surfaced to the facade, not
        raised here.
        """
        try:
            response = self._send_raw(message)
        except DaemonNotRunningError:
            if not self._auto_start:
                raise
            self._spawn()
            self._wait_bridge()
            response = self._send_raw(message)  # retry once after starting

        if _error(response) == _NO_BRIDGE and self._auto_start:
            self.start()  # wait for a booting bridge, or replace a wedged daemon
            response = self._send_raw(message)  # retry once after recovery
        return response

    # -- lifecycle -------------------------------------------------------------
    def _spawn(self) -> None:
        """Launch the daemon detached, so it survives this process exiting."""
        if sys.platform != "darwin":
            raise ApwError(
                Status.GENERIC_ERROR,
                "apwlib requires macOS (the Apple Passwords helper is macOS-only)",
            )
        ensure_data_dir()
        _rotate_log()
        log = open(LOG_PATH, "a")  # noqa: SIM115 (handed to the child; closed on our exit)
        subprocess.Popen(
            [sys.executable, "-m", "apwlib.daemon"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,  # detach from our session/pgroup; survives SIGHUP
            close_fds=True,
        )

    def _bridge_ready(self) -> bool:
        try:
            return bool(self._send_raw({"op": "status"}).get("bridge"))
        except DaemonNotRunningError:
            return False

    def _wait_bridge(self, timeout: float = _START_TIMEOUT) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._bridge_ready():
                return True
            time.sleep(0.3)
        return False

    def _wait_stopped(self, timeout: float = 10.0) -> bool:
        """Block until the socket refuses connections (the daemon is gone, lock released).

        A daemon mid-shutdown may still accept a connection but close it without a reply
        (an empty, unparseable response); that means "still stopping" — keep polling until
        the connection is refused outright, so a subsequent spawn won't lose the lock race.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self._send_raw({"op": "status"})
            except DaemonNotRunningError:
                return True
            except ValueError:
                pass  # half-open socket during shutdown; not gone yet
            time.sleep(0.1)
        return False

    def start(self) -> bool:
        """Ensure a daemon with a connected bridge is running.

        Auto-spawns if none is running. If a daemon is running but its bridge is dead
        (a wedged singleton — e.g. the browser was closed), it is stopped and replaced,
        since a fresh spawn would otherwise just lose the lock race and exit.
        """
        status = self.status()
        if status["running"] and status["bridge"]:
            return True
        if status["running"]:  # alive but unhealthy — replace it rather than defer to it
            self.stop()
            self._wait_stopped()
        self._spawn()
        return self._wait_bridge()

    def stop(self) -> bool:
        """Ask a running daemon to shut down. Returns False if none was running."""
        try:
            self._send_raw({"op": "stop"})
            return True
        except SessionError:
            return False

    def restart(self) -> bool:
        """Stop any running daemon and start a fresh one. Returns True if the bridge came up."""
        self.stop()
        self._wait_stopped()
        self._spawn()
        return self._wait_bridge()

    def status(self) -> dict[str, bool]:
        """Report daemon reachability, bridge connectivity, and pairing (does not auto-start)."""
        try:
            resp = self._send_raw({"op": "status"})
        except SessionError:
            return {"running": False, "bridge": False, "paired": False}
        return {
            "running": True,
            "bridge": bool(resp.get("bridge")),
            "paired": bool(resp.get("paired")),
        }

    # -- pairing primitives ----------------------------------------------------
    def request_challenge(self) -> None:
        """Ask the extension to display the macOS pairing PIN."""
        self.deliver({"cmd": Command.HANDSHAKE})

    def verify_challenge(self, pin: str) -> None:
        """Submit the PIN. Pairing completes asynchronously — see :meth:`wait_until_paired`."""
        self.deliver({"cmd": Command.HANDSHAKE, "pin": pin})

    def wait_until_paired(self, timeout: float = _PAIR_TIMEOUT) -> bool:
        """Block until the daemon reports a paired session, or ``timeout`` elapses."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self._send_raw({"op": "status"}).get("paired"):
                    return True
            except DaemonNotRunningError:
                return False
            time.sleep(0.2)
        return False


class ApplePasswords:
    """Read and write Apple Passwords (iCloud Keychain) via a managed daemon.

    The daemon (a headless browser hosting the iCloud Passwords extension) is auto-started
    on first use as a detached singleton and reused thereafter — see :attr:`daemon` for
    explicit control. Pairing needs a one-time PIN: if ``pin_provider`` is given, an
    unpaired request transparently pairs (pops the macOS dialog, calls ``pin_provider()``,
    retries); otherwise it raises ``NotPairedError``.

    Pass ``auto_start=False`` to require an already-running daemon.
    """

    def __init__(
        self,
        socket_path: str | None = None,
        auto_start: bool = True,
        pin_provider: Callable[[], str] | None = None,
    ) -> None:
        self.daemon = _Daemon(socket_path or str(SOCKET_PATH), auto_start)
        self._pin_provider = pin_provider

    # -- request plumbing ------------------------------------------------------
    def _send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Deliver a message, auto-pairing on an unpaired session when possible."""
        response = self.daemon.deliver(message)
        if _error(response) == _UNPAIRED:
            if self._pin_provider and message.get("cmd") != Command.HANDSHAKE:
                self._pair()
                response = self.daemon.deliver(message)  # retry once after pairing
            if _error(response) == _UNPAIRED:
                raise NotPairedError(Status.INVALID_SESSION, "session is not paired")
        return response

    def _pair(self) -> None:
        """Pop the PIN dialog, collect the PIN, verify, and wait for pairing to complete."""
        if not self._pin_provider:
            return
        self.daemon.request_challenge()
        self.daemon.verify_challenge(str(self._pin_provider()))
        self.daemon.wait_until_paired()

    def _payload(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._send(message)
        if "data" not in response:
            raise error_for(response.get("status", Status.SERVER_ERROR), response.get("error"))
        return protocol.entries_from(response["data"])

    def _ok(self, message: dict[str, Any]) -> None:
        response = self._send(message)
        status = response.get("data", {}).get("STATUS", response.get("status"))
        if status not in (None, Status.SUCCESS):
            raise error_for(status, response.get("error"))

    # -- passwords -------------------------------------------------------------
    def get_login_names(self, url: str) -> list[PasswordEntry]:
        _require_url(url)
        return [
            PasswordEntry.from_raw(e) for e in self._payload(protocol.get_login_names_for_url(url))
        ]

    def get_password(self, url: str, login: str = "") -> list[PasswordEntry]:
        _require_url(url)
        return [
            PasswordEntry.from_raw(e)
            for e in self._payload(protocol.get_password_for_url(url, login))
        ]

    def save_account(self, url: str, login: str, password: str) -> None:
        _require_url(url)
        self._ok(protocol.save_account_for_url(url, login, password))

    # -- one-time codes --------------------------------------------------------
    def get_otp(self, url: str) -> list[OTPEntry]:
        _require_url(url)
        return [OTPEntry.from_raw(e) for e in self._payload(protocol.get_otp_for_url(url))]

    def list_otp(self, url: str) -> list[OTPEntry]:
        _require_url(url)
        return [OTPEntry.from_raw(e) for e in self._payload(protocol.list_otp_for_url(url))]


def _require_url(url: str) -> None:
    if not url:
        raise ApwError(Status.INVALID_PARAM, "URL is required")
