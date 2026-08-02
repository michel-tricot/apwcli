"""Client transport: error distinction and single-retry behavior (no real daemon)."""

import sys
from pathlib import Path

import pytest
from apwlib import ApplePasswords, ApwError, Daemon, DaemonNotRunningError, DaemonStartError, NotPairedError
from apwlib._protocol import Status


def test_no_daemon_raises_daemon_not_running() -> None:
    # A socket path that cannot connect, with auto-start disabled, must surface as
    # DaemonNotRunningError (not a generic session error).
    pw = ApplePasswords(socket_path="/tmp/apwlib-does-not-exist.sock", auto_start=False)
    with pytest.raises(DaemonNotRunningError):
        pw.list_accounts("github.com")


def test_unpaired_response_raises_not_paired(monkeypatch: pytest.MonkeyPatch) -> None:
    pw = ApplePasswords(auto_start=False)
    monkeypatch.setattr(
        pw._daemon,
        "_send_raw",
        lambda _msg: {"id": "1", "status": int(Status.INVALID_SESSION), "error": "unpaired"},
    )
    with pytest.raises(NotPairedError):
        pw.list_accounts("github.com")


def test_autopair_on_unpaired(monkeypatch: pytest.MonkeyPatch) -> None:
    prompted = []
    pw = ApplePasswords(auto_start=False, pin_provider=lambda: (prompted.append(1), "123456")[1])
    state = {"paired": False}

    def fake_send_raw(msg):
        if msg.get("op") == "pair_challenge":
            return {"ready": True}
        if msg.get("op") == "pair_verify":
            state["paired"] = msg.get("pin") == "123456"
            return {"paired": state["paired"]}
        if not state["paired"]:
            return {"id": "1", "status": int(Status.INVALID_SESSION), "error": "unpaired"}
        return {
            "id": "1",
            "data": {"STATUS": int(Status.SUCCESS), "Entries": [{"USR": "me", "sites": ["x"]}]},
        }

    monkeypatch.setattr(pw._daemon, "_send_raw", fake_send_raw)
    result = pw.list_accounts("github.com")
    assert prompted  # the PIN provider was invoked
    assert [e.username for e in result] == ["me"]


def test_unpaired_without_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    pw = ApplePasswords(auto_start=False)  # no pin_provider
    monkeypatch.setattr(
        pw._daemon,
        "_send_raw",
        lambda _m: {"id": "1", "status": int(Status.INVALID_SESSION), "error": "unpaired"},
    )
    with pytest.raises(NotPairedError):
        pw.list_accounts("github.com")


def test_daemon_lost_mid_request_raises_session_error() -> None:
    # A daemon that accepts the connection but hangs up without replying must surface
    # as SessionError — not a raw JSONDecodeError, and not DaemonNotRunningError
    # (deliver()'s auto-start retry could re-send a request that already executed).
    import socket
    import threading

    from apwlib._errors import SessionError

    # /tmp, not tmp_path: macOS caps AF_UNIX socket paths at ~104 bytes.
    sock_path = "/tmp/apwlib-test-hangup.sock"
    Path(sock_path).unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(1)

    def hang_up() -> None:
        conn, _ = server.accept()
        conn.close()  # reply-less close: the client reads EOF

    thread = threading.Thread(target=hang_up, daemon=True)
    thread.start()
    try:
        pw = ApplePasswords(socket_path=sock_path, auto_start=False)
        with pytest.raises(SessionError) as excinfo:
            pw.list_accounts("github.com")
        assert not isinstance(excinfo.value, DaemonNotRunningError)
    finally:
        thread.join(timeout=5)
        server.close()
        Path(sock_path).unlink(missing_ok=True)


def test_no_daemon_autostart_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    pw = ApplePasswords()  # auto_start=True
    calls = {"raw": 0, "start": 0}

    def fake_send_raw(_msg):
        calls["raw"] += 1
        if calls["raw"] == 1:
            raise DaemonNotRunningError("daemon not running")
        return {"id": "1", "data": {"STATUS": int(Status.SUCCESS), "Entries": []}}

    monkeypatch.setattr(pw._daemon, "_send_raw", fake_send_raw)
    monkeypatch.setattr(pw._daemon, "start", lambda: calls.__setitem__("start", calls["start"] + 1) or True)

    assert pw.list_accounts("github.com") == []
    assert calls == {"raw": 2, "start": 1}  # started once, retried once


def test_spawn_off_macos_fails_with_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    pw = ApplePasswords(socket_path="/tmp/apwlib-does-not-exist.sock")  # auto_start=True
    with pytest.raises(ApwError, match="macOS"):
        pw.list_accounts("github.com")


def test_autostart_without_browser_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    # Auto-start must report "no supported browser" immediately, not spawn a daemon that
    # dies and leave the caller waiting on a bridge that never comes.
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("apwlib._browsers.installed_browsers", list)
    spawned = []
    pw = ApplePasswords(socket_path="/tmp/apwlib-does-not-exist.sock")  # auto_start=True
    monkeypatch.setattr(pw._daemon, "_wait_stopped", lambda *a, **k: True)
    monkeypatch.setattr(pw._daemon, "_wait_bridge", lambda *a, **k: spawned.append("waited") or True)
    with pytest.raises(ApwError, match="no supported browser"):
        pw.list_accounts("github.com")
    assert spawned == []  # failed before launching/waiting on anything


def test_start_noop_when_daemon_running(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = Daemon(auto_start=False)
    spawned = []
    monkeypatch.setattr(daemon, "status", lambda: {"running": True, "bridge": True, "paired": True})
    monkeypatch.setattr(daemon, "_wait_bridge", lambda *a, **k: True)
    monkeypatch.setattr(daemon, "_spawn", lambda: spawned.append(1))

    daemon.start()  # no raise
    assert spawned == []  # a running daemon is left alone


def test_start_waits_out_a_stopping_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    # `stop` immediately followed by `start` must work: the stopping daemon releases
    # its singleton lock last, so start() waits for the lock before spawning.
    daemon = Daemon(auto_start=False)
    order = []
    monkeypatch.setattr(daemon, "status", lambda: {"running": False, "bridge": False, "paired": False})
    monkeypatch.setattr(daemon, "_wait_stopped", lambda *a, **k: order.append("waited") or True)
    monkeypatch.setattr(daemon, "_spawn", lambda *a, **k: order.append("spawned"))
    monkeypatch.setattr(daemon, "_wait_bridge", lambda *a, **k: True)

    daemon.start()
    assert order == ["waited", "spawned"]


def test_start_rejects_unknown_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    # An unknown/uninstalled browser id must fail before spawning a daemon that
    # would just die on startup.
    from apwlib._browsers import BrowserInfo

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        "apwlib._browsers.installed_browsers",
        lambda: [BrowserInfo(id="chrome", name="Chrome", binary=Path("/x"))],
    )
    daemon = Daemon(auto_start=False)
    monkeypatch.setattr(daemon, "status", lambda: {"running": False, "bridge": False, "paired": False})
    monkeypatch.setattr(daemon, "_wait_stopped", lambda *a, **k: True)
    with pytest.raises(ApwError, match="browser not available"):
        daemon.start("netscape")


def test_restart_rejects_unknown_browser_before_stopping(monkeypatch: pytest.MonkeyPatch) -> None:
    # A typo'd -b must not take down a healthy daemon: validate before the stop.
    from apwlib._browsers import BrowserInfo

    monkeypatch.setattr(
        "apwlib._browsers.installed_browsers",
        lambda: [BrowserInfo(id="chrome", name="Chrome", binary=Path("/x"))],
    )
    daemon = Daemon(auto_start=False)
    stopped: list = []
    monkeypatch.setattr(daemon, "stop", lambda: stopped.append(1))
    with pytest.raises(ApwError, match="browser not available"):
        daemon.restart("netscape")
    assert stopped == []


def test_start_with_browser_refuses_running_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    # An explicit browser needs a fresh daemon; a silent no-op would look like success.
    from apwlib._browsers import BrowserInfo

    monkeypatch.setattr(
        "apwlib._browsers.installed_browsers",
        lambda: [BrowserInfo(id="chrome", name="Chrome", binary=Path("/x"))],
    )
    daemon = Daemon(auto_start=False)
    monkeypatch.setattr(daemon, "status", lambda: {"running": True, "bridge": True, "paired": True, "browser": "Brave", "browser_pid": 7})
    with pytest.raises(ApwError, match="already running"):
        daemon.start("chrome")


def test_start_raises_when_bridge_never_comes(monkeypatch: pytest.MonkeyPatch) -> None:
    # A spawned daemon whose bridge never connects is an error with a pointer at the
    # log — not a silent False the caller has to translate.
    daemon = Daemon(auto_start=False)
    monkeypatch.setattr(daemon, "status", lambda: {"running": False, "bridge": False, "paired": False})
    monkeypatch.setattr(daemon, "_wait_stopped", lambda *a, **k: True)
    monkeypatch.setattr(daemon, "_spawn", lambda *a, **k: None)
    monkeypatch.setattr(daemon, "_wait_bridge", lambda *a, **k: False)
    with pytest.raises(DaemonStartError, match=r"daemon\.log"):
        daemon.start()


def test_singleton_free_detects_lock_holder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import fcntl
    import os

    from apwlib import _client as client

    lock = tmp_path / "daemon.lock"
    monkeypatch.setattr(client, "LOCK_PATH", lock)
    daemon = Daemon(auto_start=False)

    assert daemon._singleton_free() is True  # nobody holds it

    held = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert daemon._singleton_free() is False  # a holder blocks acquisition
    finally:
        fcntl.flock(held, fcntl.LOCK_UN)
        os.close(held)

    assert daemon._singleton_free() is True  # freed again


def test_verify_challenge_returns_the_daemon_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    # The daemon owns the pairing waits; verify_challenge is one blocking op whose
    # reply carries the outcome.
    daemon = Daemon(auto_start=False)
    sent: list[dict] = []
    monkeypatch.setattr(daemon, "_send_raw", lambda m: sent.append(m) or {"paired": False})
    assert daemon.verify_challenge("123456") is False
    assert sent == [{"op": "pair_verify", "pin": "123456"}]

    monkeypatch.setattr(daemon, "_send_raw", lambda _m: {"paired": True})
    assert daemon.verify_challenge("123456") is True


def test_pairing_ops_raise_on_daemon_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # A pairing step that fails outright (e.g. no extension connected) must raise the
    # mapped error, not read as a rejected PIN.
    from apwlib import SessionError

    daemon = Daemon(auto_start=False)
    error = {"status": int(Status.INVALID_SESSION), "error": "no extension connected"}
    monkeypatch.setattr(daemon, "_send_raw", lambda _m: error)
    with pytest.raises(SessionError):
        daemon.request_challenge()
    with pytest.raises(SessionError):
        daemon.verify_challenge("123456")
