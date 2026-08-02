import pytest
from apwlib import Status
from apwlib._errors import ApwError
from apwlib._protocol import (
    Action,
    Command,
    entries_from,
    get_login_names_for_url,
    get_otp_for_url,
    get_password_for_url,
    save_account_for_url,
)


def test_get_login_names_builder() -> None:
    msg = get_login_names_for_url("https://github.com")
    assert msg["cmd"] == Command.GET_LOGIN_NAMES_FOR_URL
    assert msg["qid"] == "CmdGetLoginNames4URL"
    assert msg["body"] == {"ACT": Action.GHOST_SEARCH, "URL": "https://github.com"}


def test_get_password_builder_includes_login() -> None:
    msg = get_password_for_url("https://github.com", "me@example.com")
    assert msg["cmd"] == Command.GET_PASSWORD_FOR_LOGIN_NAME
    assert msg["body"]["USR"] == "me@example.com"


def test_save_builder_uses_new_fields() -> None:
    msg = save_account_for_url("https://x.com", "user", "secret")
    assert msg["body"]["NURL"] == "https://x.com"
    assert msg["body"]["NUSR"] == "user"
    assert msg["body"]["NPWD"] == "secret"


def test_otp_builder_adds_scheme() -> None:
    msg = get_otp_for_url("example.com")
    assert msg["body"]["frameURLs"] == ["http://example.com"]


def test_entries_from_array() -> None:
    data = {"STATUS": Status.SUCCESS, "Entries": [{"USR": "a"}, {"USR": "b"}]}
    assert entries_from(data) == [{"USR": "a"}, {"USR": "b"}]


def test_entries_from_keyed_and_sorted() -> None:
    data = {"STATUS": Status.SUCCESS, "Entry_10": {"USR": "k"}, "Entry_2": {"USR": "b"}}
    assert [e["USR"] for e in entries_from(data)] == ["b", "k"]


def test_entries_from_no_results_is_empty() -> None:
    assert entries_from({"STATUS": Status.NO_RESULTS}) == []


def test_entries_from_error_status_raises() -> None:
    with pytest.raises(ApwError):
        entries_from({"STATUS": Status.INVALID_SESSION})


def test_bridge_challenge_resets_any_active_session() -> None:
    # A (re)challenge must reset from ANY active state, including SessionKeySet — else an
    # already-paired session shows no new PIN and a wrong PIN falsely reports "paired".
    from importlib.resources import files

    bridge = files("apwlib.daemon").joinpath("bridge.js").read_text()
    assert "g_theState !== ContextState.NotInSession" in bridge
    assert "resetTheSession(ContextState.NotInSession)" in bridge
