"""Client transport: error distinction and single-retry behavior (no real daemon)."""

import sys
from pathlib import Path

import pytest
from apwlib import ApplePasswords, ApwError, DaemonNotRunningError, NotPairedError
from apwlib.protocol import Status


def test_no_daemon_raises_daemon_not_running() -> None:
    # A socket path that cannot connect, with auto-start disabled, must surface as
    # DaemonNotRunningError (not a generic session error).
    pw = ApplePasswords(socket_path="/tmp/apwlib-does-not-exist.sock", auto_start=False)
    with pytest.raises(DaemonNotRunningError):
        pw.get_login_names("github.com")


def test_unpaired_response_raises_not_paired(monkeypatch: pytest.MonkeyPatch) -> None:
    pw = ApplePasswords(auto_start=False)
    monkeypatch.setattr(
        pw.daemon,
        "_send_raw",
        lambda _msg: {"id": "1", "status": int(Status.INVALID_SESSION), "error": "unpaired"},
    )
    with pytest.raises(NotPairedError):
        pw.get_login_names("github.com")


def test_autopair_on_unpaired(monkeypatch: pytest.MonkeyPatch) -> None:
    prompted = []
    pw = ApplePasswords(auto_start=False, pin_provider=lambda: (prompted.append(1), "123456")[1])
    state = {"paired": False}

    def fake_send_raw(msg):
        if msg.get("op") == "status":  # wait_until_paired polls this
            return {"running": True, "bridge": True, "paired": state["paired"]}
        if msg.get("cmd") == 2:  # handshake (challenge or verify)
            if msg.get("pin") is not None:
                state["paired"] = True
            return {"id": "1", "status": int(Status.SUCCESS)}
        if not state["paired"]:
            return {"id": "1", "status": int(Status.INVALID_SESSION), "error": "unpaired"}
        return {
            "id": "1",
            "data": {"STATUS": int(Status.SUCCESS), "Entries": [{"USR": "me", "sites": ["x"]}]},
        }

    monkeypatch.setattr(pw.daemon, "_send_raw", fake_send_raw)
    result = pw.get_login_names("github.com")
    assert prompted  # the PIN provider was invoked
    assert [e.username for e in result] == ["me"]


def test_unpaired_without_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    pw = ApplePasswords(auto_start=False)  # no pin_provider
    monkeypatch.setattr(
        pw.daemon,
        "_send_raw",
        lambda _m: {"id": "1", "status": int(Status.INVALID_SESSION), "error": "unpaired"},
    )
    with pytest.raises(NotPairedError):
        pw.get_login_names("github.com")


def test_no_daemon_autostart_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    pw = ApplePasswords()  # auto_start=True
    calls = {"raw": 0, "spawn": 0, "wait": 0}

    def fake_send_raw(_msg):
        calls["raw"] += 1
        if calls["raw"] == 1:
            raise DaemonNotRunningError(Status.INVALID_SESSION, "daemon not running")
        return {"id": "1", "data": {"STATUS": int(Status.SUCCESS), "Entries": []}}

    monkeypatch.setattr(pw.daemon, "_send_raw", fake_send_raw)
    monkeypatch.setattr(pw.daemon, "_spawn", lambda: calls.__setitem__("spawn", calls["spawn"] + 1))
    monkeypatch.setattr(
        pw.daemon,
        "_wait_bridge",
        lambda *a, **k: calls.__setitem__("wait", calls["wait"] + 1) or True,
    )

    assert pw.get_login_names("github.com") == []
    assert calls == {"raw": 2, "spawn": 1, "wait": 1}  # started once, retried once


def test_spawn_off_macos_fails_with_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    pw = ApplePasswords(socket_path="/tmp/apwlib-does-not-exist.sock")  # auto_start=True
    with pytest.raises(ApwError, match="macOS"):
        pw.get_login_names("github.com")


def test_autostart_without_browser_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    # Auto-start must report "no supported browser" immediately, not spawn a daemon that
    # dies and leave the caller waiting on a bridge that never comes.
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("apwlib.browsers.installed_browsers", lambda: [])
    spawned = []
    pw = ApplePasswords(socket_path="/tmp/apwlib-does-not-exist.sock")  # auto_start=True
    monkeypatch.setattr(pw.daemon, "_wait_bridge", lambda *a, **k: spawned.append("waited") or True)
    with pytest.raises(ApwError, match="no supported browser"):
        pw.get_login_names("github.com")
    assert spawned == []  # failed before launching/waiting on anything


def test_start_replaces_a_wedged_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    # A daemon that is running but whose bridge is dead must be stopped and replaced,
    # not deferred to (a fresh spawn would just lose the lock race).
    daemon = ApplePasswords(auto_start=False).daemon
    calls = {"stop": 0, "spawn": 0}
    monkeypatch.setattr(
        daemon, "status", lambda: {"running": True, "bridge": False, "paired": False}
    )
    monkeypatch.setattr(
        daemon, "stop", lambda: calls.__setitem__("stop", calls["stop"] + 1) or True
    )
    monkeypatch.setattr(daemon, "_wait_stopped", lambda *a, **k: True)
    monkeypatch.setattr(daemon, "_spawn", lambda: calls.__setitem__("spawn", calls["spawn"] + 1))
    monkeypatch.setattr(daemon, "_wait_bridge", lambda *a, **k: True)

    assert daemon.start() is True
    assert calls == {"stop": 1, "spawn": 1}


def test_start_noop_when_bridge_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = ApplePasswords(auto_start=False).daemon
    spawned = []
    monkeypatch.setattr(daemon, "status", lambda: {"running": True, "bridge": True, "paired": True})
    monkeypatch.setattr(daemon, "_spawn", lambda: spawned.append(1))

    assert daemon.start() is True
    assert spawned == []  # a healthy daemon is left alone


def test_singleton_free_detects_lock_holder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import fcntl
    import os

    from apwlib import client

    lock = tmp_path / "daemon.lock"
    monkeypatch.setattr(client, "LOCK_PATH", lock)
    daemon = ApplePasswords(auto_start=False).daemon

    assert daemon._singleton_free() is True  # nobody holds it

    held = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert daemon._singleton_free() is False  # a holder blocks acquisition
    finally:
        fcntl.flock(held, fcntl.LOCK_UN)
        os.close(held)

    assert daemon._singleton_free() is True  # freed again


def test_wait_until_paired_fails_fast_on_collapsed_handshake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A handshake in progress (MSG1Set) that falls back to NotInSession means the PIN was
    # rejected — return False at once, not after the full timeout.
    daemon = ApplePasswords(auto_start=False).daemon
    responses = iter(
        [
            {"paired": False, "pairing_state": "MSG1Set"},
            {"paired": False, "pairing_state": "NotInSession"},
        ]
    )
    monkeypatch.setattr(daemon, "_send_raw", lambda _m: next(responses))
    assert daemon.wait_until_paired(timeout=10) is False


def test_wait_until_paired_true_when_paired(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = ApplePasswords(auto_start=False).daemon
    monkeypatch.setattr(daemon, "_send_raw", lambda _m: {"paired": True})
    assert daemon.wait_until_paired(timeout=1) is True
