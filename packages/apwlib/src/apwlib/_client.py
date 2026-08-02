"""Synchronous facade — the public API. Talks to the daemon's unix socket."""

from __future__ import annotations

import fcntl
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

from apwlib import _protocol as protocol
from apwlib._errors import (
    ApwError,
    DaemonNotRunningError,
    DaemonStartError,
    NotPairedError,
    SessionError,
    error_for,
)
from apwlib._models import OTPEntry, PasswordEntry
from apwlib._paths import LOCK_PATH, LOG_PATH, SOCKET_PATH, ensure_data_dir
from apwlib._protocol import WIRE_UNPAIRED, Status


class DaemonStatus(TypedDict):
    """The shape of :meth:`Daemon.status`; keeps its two return paths in sync."""

    running: bool
    bridge: bool
    paired: bool
    browser: str | None
    browser_pid: int | None


_TIMEOUT = 35.0  # above the daemon's own waits (30s bridge requests, 20s pairing)
_START_TIMEOUT = 45.0  # browser launch + extension load + bridge connect
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


class Daemon:
    """The connection to the background daemon: transport, lifecycle, and pairing.

    ``ApplePasswords`` manages one internally (auto-start, auto-pair); construct your
    own only for explicit lifecycle control — it backs ``apwcli daemon
    start/stop/status/pair``.
    """

    def __init__(self, socket_path: str | Path | None = None, auto_start: bool = True) -> None:
        self._socket_path = str(socket_path or SOCKET_PATH)
        self._auto_start = auto_start

    @property
    def log_path(self) -> Path:
        """Where the detached daemon writes its log."""
        return LOG_PATH

    # -- transport -------------------------------------------------------------
    def _send_raw(self, message: dict[str, Any]) -> dict[str, Any]:
        """Send one message. Raises ``DaemonNotRunningError`` if the socket is unreachable."""
        try:
            conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.settimeout(_TIMEOUT)
            conn.connect(self._socket_path)
        except OSError as exc:
            raise DaemonNotRunningError("daemon not running") from exc
        try:
            conn.sendall((json.dumps(message) + "\n").encode())
            buffer = b""
            while b"\n" not in buffer:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buffer += chunk
            return json.loads(buffer.split(b"\n", 1)[0])
        except (OSError, json.JSONDecodeError) as exc:
            # The daemon went away mid-request (empty/truncated reply, reset, or
            # timeout). Deliberately NOT DaemonNotRunningError: the request may
            # already have executed, so _deliver()'s auto-start retry must not
            # re-send it.
            raise SessionError("daemon connection lost mid-request") from exc
        finally:
            conn.close()

    def _deliver(self, message: dict[str, Any]) -> dict[str, Any]:
        """Deliver a message, auto-starting the daemon (if enabled) when none answers.

        One start, one retry — anything still wrong after that surfaces as the error
        it is (`apwcli daemon restart` is the manual recovery). Returns the raw
        response; an ``unpaired`` response is surfaced to the facade, not raised here.
        """
        try:
            return self._send_raw(message)
        except DaemonNotRunningError:
            if not self._auto_start:
                raise
            self.start()
            return self._send_raw(message)  # retry once after starting

    # -- lifecycle -------------------------------------------------------------
    def _spawn(self, browser: str | None = None) -> None:
        """Launch the daemon detached, so it survives this process exiting."""
        if sys.platform != "darwin":
            raise ApwError(
                Status.GENERIC_ERROR,
                "apwlib requires macOS (the Apple Passwords helper is macOS-only)",
            )
        # Preflight: without a browser the detached daemon would just die on startup, and the
        # caller would wait out _wait_bridge and get a misleading "daemon not running". Fail
        # fast here so every entry point (auto-start included) reports the real cause.
        from apwlib._browsers import BROWSERS, installed_browsers

        if not installed_browsers():
            names = ", ".join(b.name for b in BROWSERS)
            raise ApwError(
                Status.GENERIC_ERROR,
                f"no supported browser found — install one of: {names} (e.g. `brew install --cask google-chrome`)",
            )
        ensure_data_dir()
        _rotate_log()
        log = LOG_PATH.open("a")  # handed to the child; closed on our exit
        subprocess.Popen(
            [sys.executable, "-m", "apwlib.daemon", *([browser] if browser else [])],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,  # detach from our session/pgroup; survives SIGHUP
            close_fds=True,
        )

    def _bridge_ready(self) -> bool:
        try:
            return bool(self._send_raw({"op": "status"}).get("bridge"))
        except SessionError:  # unreachable, or lost mid-poll — either way not ready
            return False

    def _wait_bridge(self, timeout: float = _START_TIMEOUT) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._bridge_ready():
                return True
            time.sleep(0.3)
        return False

    def _singleton_free(self) -> bool:
        """True if the daemon's singleton lock can be taken (no daemon holds it)."""
        try:
            fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
        except FileNotFoundError:
            return True  # no data dir yet -> nothing can be holding the lock
        except OSError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)  # release at once; the next daemon takes it
            return True
        except OSError:
            return False
        finally:
            os.close(fd)

    def _wait_stopped(self, timeout: float = 10.0) -> bool:
        """Block until the daemon has fully exited and released its singleton lock.

        Keying on the lock (not the socket) matters: on shutdown the daemon closes the
        socket first but releases the lock last, after terminating the browser. A spawn
        in that window would lose the lock race and exit as "already running", so we wait
        for the lock to actually free.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._singleton_free():
                return True
            time.sleep(0.1)
        return False

    def _require_bridge(self) -> None:
        if not self._wait_bridge():
            raise DaemonStartError(f"daemon did not become ready; see {LOG_PATH}")

    def _validate_browser(self, browser: str | None) -> None:
        """Reject an unknown/uninstalled browser id up front — before any stop or spawn."""
        if browser is None:
            return
        from apwlib._browsers import installed_browsers, resolve_browser

        if resolve_browser(browser) is None:
            ids = ", ".join(b.id for b in installed_browsers())
            hint = f" (installed: {ids})" if ids else ""
            raise ApwError(Status.INVALID_PARAM, f"browser not available: {browser}{hint}")

    def start(self, browser: str | None = None) -> None:
        """Ensure a daemon is running with its bridge connected.

        A no-op when one is already reachable — except with an explicit ``browser``,
        which needs a fresh daemon and raises instead (use :meth:`restart`). Otherwise
        spawns one — after waiting out a stopping daemon's singleton lock, so `stop`
        immediately followed by `start` works. ``browser`` applies to that daemon only
        (it is not persisted). Raises ``DaemonStartError`` if the bridge does not come
        up, and ``ApwError`` when no supported browser is installed.
        """
        self._validate_browser(browser)
        status = self.status()
        if status["running"]:
            if browser is not None:
                raise ApwError(
                    Status.INVALID_PARAM,
                    f"daemon already running with {status['browser']} — restart to switch browsers",
                )
            self._require_bridge()
            return
        self._wait_stopped()  # a stopping daemon releases the lock last
        self._spawn(browser)
        self._require_bridge()

    def stop(self) -> bool:
        """Ask a running daemon to shut down. Returns False if none was running."""
        try:
            self._send_raw({"op": "stop"})
            return True
        except SessionError:
            return False

    def restart(self, browser: str | None = None) -> None:
        """Stop any running daemon and start a fresh one (raises like :meth:`start`)."""
        self._validate_browser(browser)  # before the stop — don't kill a daemon for a typo
        self.stop()
        self._wait_stopped()
        self._spawn(browser)
        self._require_bridge()

    def status(self) -> DaemonStatus:
        """Report daemon reachability, bridge connectivity, and pairing (does not auto-start).

        When running, also reports ``browser`` (the managed browser's name) and
        ``browser_pid`` (its process id); both are ``None`` otherwise.
        """
        try:
            resp: dict[str, Any] = self._send_raw({"op": "status"})
        except SessionError:  # unreachable, or lost mid-poll — either way not running
            resp = {}
        return {
            "running": bool(resp),
            "bridge": bool(resp.get("bridge")),
            "paired": bool(resp.get("paired")),
            "browser": resp.get("browser"),
            "browser_pid": resp.get("browser_pid"),
        }

    # -- pairing primitives ----------------------------------------------------
    # The daemon owns the waits around the handshake (see daemon/server.py); each
    # step here is one blocking request that returns when the step has settled.

    def request_challenge(self) -> None:
        """Ask the extension to display the macOS pairing PIN.

        Returns once the handshake is ready for the PIN, so :meth:`verify_challenge`
        can be called immediately. Raises if the daemon/extension can't pair at all.
        """
        response = self._deliver({"op": "pair_challenge"})
        if _error(response):
            raise error_for(response.get("status", Status.SERVER_ERROR), response.get("error"))

    def verify_challenge(self, pin: str) -> bool:
        """Submit the PIN and block until pairing settles; True once paired.

        False means the helper rejected the PIN (reported the moment the handshake
        collapses) or the attempt timed out daemon-side.
        """
        response = self._deliver({"op": "pair_verify", "pin": str(pin)})
        if _error(response):
            raise error_for(response.get("status", Status.SERVER_ERROR), response.get("error"))
        return bool(response.get("paired"))


class ApplePasswords:
    """Read and write Apple Passwords (iCloud Keychain) via a managed daemon.

    The daemon (a headless browser hosting the iCloud Passwords extension) is auto-started
    on first use as a detached singleton and reused thereafter; use :class:`Daemon` for
    explicit lifecycle control. Pairing needs a one-time PIN: if ``pin_provider`` is given,
    an unpaired request transparently pairs (pops the macOS dialog, calls
    ``pin_provider()``, retries); otherwise it raises ``NotPairedError``.

    Pass ``auto_start=False`` to require an already-running daemon.
    """

    def __init__(
        self,
        socket_path: str | Path | None = None,
        auto_start: bool = True,
        pin_provider: Callable[[], str] | None = None,
    ) -> None:
        self._daemon = Daemon(socket_path, auto_start)
        self._pin_provider = pin_provider

    # -- request plumbing ------------------------------------------------------
    def _send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Deliver a message, auto-pairing on an unpaired session when possible."""
        response = self._daemon._deliver(message)
        if _error(response) == WIRE_UNPAIRED:
            if self._pin_provider:
                self._pair()
                response = self._daemon._deliver(message)  # retry once after pairing
            if _error(response) == WIRE_UNPAIRED:
                raise NotPairedError("session is not paired")
        return response

    def _pair(self) -> None:
        """Pop the PIN dialog, collect the PIN, and verify (blocks until settled)."""
        if not self._pin_provider:
            return
        self._daemon.request_challenge()
        self._daemon.verify_challenge(str(self._pin_provider()))

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
    def list_accounts(self, url: str) -> list[PasswordEntry]:
        """The accounts saved for a site (usernames only, never passwords)."""
        _require_url(url)
        return [PasswordEntry._from_raw(e) for e in self._payload(protocol.get_login_names_for_url(url))]

    def get_password(self, url: str, username: str | None = None) -> list[PasswordEntry]:
        """Password entries for a site, optionally restricted to ``username``."""
        _require_url(url)
        return [PasswordEntry._from_raw(e) for e in self._payload(protocol.get_password_for_url(url, username or ""))]

    def save_password(self, url: str, username: str, password: str) -> None:
        """Create or update a credential."""
        _require_url(url)
        self._ok(protocol.save_account_for_url(url, username, password))

    # -- one-time codes --------------------------------------------------------
    def get_otp(self, url: str) -> list[OTPEntry]:
        """The current one-time code(s) for a site."""
        _require_url(url)
        return [OTPEntry._from_raw(e) for e in self._payload(protocol.get_otp_for_url(url))]

    def list_otp(self, url: str) -> list[OTPEntry]:
        """The accounts that have one-time codes for a site (no codes)."""
        _require_url(url)
        return [OTPEntry._from_raw(e) for e in self._payload(protocol.list_otp_for_url(url))]


def _require_url(url: str) -> None:
    if not url:
        raise ApwError(Status.INVALID_PARAM, "URL is required")
