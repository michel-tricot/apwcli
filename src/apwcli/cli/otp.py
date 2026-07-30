"""One-time-code commands (the `otp` group)."""

from __future__ import annotations

import typer
from apwlib import ApwError

from apwcli.cli.common import (
    CLIPBOARD_CLEAR_SECONDS,
    ClearAfterOption,
    Format,
    FormatOption,
    client,
    copy_secret,
    emit,
    fail,
    otp_app,
)


@otp_app.command("get")
def otp_get(
    url: str,
    fmt: FormatOption = Format.table,
    clipboard: bool = typer.Option(
        False, "--clipboard", "-c", help="Copy the code to the clipboard, print nothing."
    ),
    clear_after: ClearAfterOption = CLIPBOARD_CLEAR_SECONDS,
) -> None:
    """Get a one-time code for a URL."""
    try:
        entries = client.get_otp(url)
    except ApwError as exc:
        fail(exc, fmt)
    if clipboard:
        copy_secret([(e.username, e.code) for e in entries], "one-time code", clear_after)
        return
    emit(entries, fmt)


@otp_app.command("list")
def otp_list(url: str, fmt: FormatOption = Format.table) -> None:
    """List available one-time codes for a URL."""
    try:
        emit(client.list_otp(url), fmt)
    except ApwError as exc:
        fail(exc, fmt)
