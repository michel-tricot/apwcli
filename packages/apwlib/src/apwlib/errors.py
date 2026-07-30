"""Error types, mapped from the protocol ``Status`` enum."""

from __future__ import annotations

from apwlib.protocol import Status

_STATUS_MESSAGES = {
    Status.SUCCESS: "Operation successful",
    Status.GENERIC_ERROR: "A generic error occurred",
    Status.INVALID_PARAM: "Invalid parameter provided",
    Status.NO_RESULTS: "No results found",
    Status.FAILED_TO_DELETE: "Failed to delete item",
    Status.FAILED_TO_UPDATE: "Failed to update item",
    Status.INVALID_MESSAGE_FORMAT: "Invalid message format",
    Status.DUPLICATE_ITEM: "Duplicate item found",
    Status.UNKNOWN_ACTION: "Unknown action requested",
    Status.INVALID_SESSION: "Daemon is not running or the session is not paired",
    Status.SERVER_ERROR: "Unexpected response from the extension",
}


class ApwError(Exception):
    """Base error carrying a protocol ``Status``."""

    def __init__(self, status: Status | int, message: str | None = None) -> None:
        self.status = Status(status) if not isinstance(status, Status) else status
        super().__init__(message or _STATUS_MESSAGES.get(self.status, "Unknown error"))


class SessionError(ApwError):
    """The daemon is not running or the session is not paired."""


class DaemonNotRunningError(SessionError):
    """No daemon is reachable on the socket (recoverable by starting one)."""


class NotPairedError(SessionError):
    """The daemon and extension are up, but no PIN pairing has been completed."""


class ServerError(ApwError):
    """The extension returned an unexpected response."""


_SUBCLASSES = {
    Status.INVALID_SESSION: SessionError,
    Status.SERVER_ERROR: ServerError,
}


def error_for(status: Status | int, message: str | None = None) -> ApwError:
    """Return the most specific ``ApwError`` subclass for ``status``."""
    status = Status(status) if not isinstance(status, Status) else status
    return _SUBCLASSES.get(status, ApwError)(status, message)
