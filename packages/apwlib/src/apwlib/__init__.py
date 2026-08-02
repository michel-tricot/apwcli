"""Programmatic access to Apple Passwords (iCloud Keychain) on macOS."""

from importlib.metadata import version

from apwlib.client import ApplePasswords, Daemon, DaemonStatus
from apwlib.errors import (
    ApwError,
    DaemonNotRunningError,
    DaemonStartError,
    NotPairedError,
    ServerError,
    SessionError,
)
from apwlib.models import OTPEntry, PasswordEntry
from apwlib.protocol import Status

__all__ = [
    "ApplePasswords",
    "ApwError",
    "Daemon",
    "DaemonNotRunningError",
    "DaemonStartError",
    "DaemonStatus",
    "NotPairedError",
    "OTPEntry",
    "PasswordEntry",
    "ServerError",
    "SessionError",
    "Status",
]
__version__ = version("apwlib")
