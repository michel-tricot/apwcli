"""Client transport: error distinction and single-retry behavior (no real daemon)."""

import pytest
from apwlib import ApplePasswords, DaemonNotRunningError, NotPairedError
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
