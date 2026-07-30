"""Programmatic access to Apple Passwords (iCloud Keychain) on macOS."""

from apwlib.client import ApplePasswords
from apwlib.errors import (
    ApwError,
    DaemonNotRunningError,
    NotPairedError,
    ServerError,
    SessionError,
)
from apwlib.models import OTPEntry, PasswordEntry
from apwlib.protocol import Status

__all__ = [
    "ApplePasswords",
    "ApwError",
    "DaemonNotRunningError",
    "NotPairedError",
    "OTPEntry",
    "PasswordEntry",
    "ServerError",
    "SessionError",
    "Status",
]
__version__ = "0.1.0"
