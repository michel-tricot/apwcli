"""Wire protocol: command/status enums, message builders, and response parsing.

The plaintext ``body`` of each message is what the in-browser extension encrypts into an
SMSG before posting it to the native helper. The daemon and bridge never inspect it.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class Command(IntEnum):
    """Commands the client sends. See docs/design/apwlib.md for the full helper vocabulary."""

    HANDSHAKE = 2
    GET_LOGIN_NAMES_FOR_URL = 4
    GET_PASSWORD_FOR_LOGIN_NAME = 5
    SET_PASSWORD_FOR_LOGIN_NAME_AND_URL = 6
    GET_ONE_TIME_CODES = 16
    DID_FILL_ONE_TIME_CODE = 17


class Action(IntEnum):
    """Search/save actions the client sends in a message body."""

    SEARCH = 2
    MAYBE_ADD = 4
    GHOST_SEARCH = 5


# Status is the full set the helper may return: error_for() maps any of these, so keep all.
class Status(IntEnum):
    SUCCESS = 0
    GENERIC_ERROR = 1
    INVALID_PARAM = 2
    NO_RESULTS = 3
    FAILED_TO_DELETE = 4
    FAILED_TO_UPDATE = 5
    INVALID_MESSAGE_FORMAT = 6
    DUPLICATE_ITEM = 7
    UNKNOWN_ACTION = 8
    INVALID_SESSION = 9
    SERVER_ERROR = 100


# Canonical wire error markers. The daemon and the facade both compare against these exact
# strings to drive recovery/pairing, so they must not drift. WIRE_NO_BRIDGE is produced by
# the daemon (server.py); WIRE_UNPAIRED is produced by the in-browser bridge (bridge.js) and
# forwarded verbatim — its literal is mirrored there and guarded by a test.
WIRE_NO_BRIDGE = "no extension connected"
WIRE_UNPAIRED = "unpaired"


def _with_scheme(url: str) -> str:
    return url if "://" in url else f"http://{url}"


def get_login_names_for_url(url: str) -> dict[str, Any]:
    return {
        "cmd": Command.GET_LOGIN_NAMES_FOR_URL,
        "qid": "CmdGetLoginNames4URL",
        "tabId": 1,
        "frameId": 1,
        "url": url,
        "body": {"ACT": Action.GHOST_SEARCH, "URL": url},
    }


def get_password_for_url(url: str, login: str = "") -> dict[str, Any]:
    return {
        "cmd": Command.GET_PASSWORD_FOR_LOGIN_NAME,
        "qid": "CmdGetPassword4LoginName",
        "tabId": 0,
        "frameId": 0,
        "url": url,
        "body": {"ACT": Action.SEARCH, "URL": url, "USR": login},
    }


def save_account_for_url(url: str, login: str, password: str) -> dict[str, Any]:
    return {
        "cmd": Command.SET_PASSWORD_FOR_LOGIN_NAME_AND_URL,
        "qid": "CmdSetPassword4LoginName_URL",
        "tabId": 0,
        "frameId": 0,
        "body": {
            "ACT": Action.MAYBE_ADD,
            "URL": "",
            "USR": "",
            "PWD": "",
            "NURL": url,
            "NUSR": login,
            "NPWD": password,
        },
    }


def get_otp_for_url(url: str) -> dict[str, Any]:
    return {
        "cmd": Command.DID_FILL_ONE_TIME_CODE,
        "qid": "CmdDidFillOneTimeCode",
        "tabId": 0,
        "frameId": 0,
        "body": {"ACT": Action.SEARCH, "TYPE": "oneTimeCodes", "frameURLs": [_with_scheme(url)]},
    }


def list_otp_for_url(url: str) -> dict[str, Any]:
    return {
        "cmd": Command.GET_ONE_TIME_CODES,
        "qid": "CmdDidFillOneTimeCode",
        "tabId": 0,
        "frameId": 0,
        "body": {
            "ACT": Action.GHOST_SEARCH,
            "TYPE": "oneTimeCodes",
            "frameURLs": [_with_scheme(url)],
        },
    }


def entries_from(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the entry list from a decrypted response payload.

    Raises ``ApwError`` for non-success, non-"no results" statuses. Entries arrive either
    as an ``Entries`` array or as ``Entry_0``…``Entry_n`` keys.
    """
    from apwlib.errors import ServerError, error_for

    status = data.get("STATUS")
    if not isinstance(status, int):
        raise ServerError(Status.SERVER_ERROR)
    if status == Status.NO_RESULTS:
        return []
    if status != Status.SUCCESS:
        raise error_for(status)
    if isinstance(data.get("Entries"), list):
        return data["Entries"]
    keyed = [(k, v) for k, v in data.items() if k.startswith("Entry_")]
    keyed.sort(key=lambda kv: int(kv[0].split("_", 1)[1]) if kv[0].split("_", 1)[1].isdigit() else 0)
    return [v for _, v in keyed]
