"""Password commands (the `pw` group)."""

from __future__ import annotations

import sys

import typer
from apwlib import ApwError

from apwcli.cli.common import (
    Format,
    FormatOption,
    client,
    copy_secret,
    emit,
    fail,
    pw_app,
    status_line,
)


@pw_app.command("list")
def pw_list(url: str, fmt: FormatOption = Format.table) -> None:
    """List accounts saved for a URL."""
    try:
        emit(client.get_login_names(url), fmt)
    except ApwError as exc:
        fail(exc, fmt)


@pw_app.command("get")
def pw_get(
    url: str,
    username: str = typer.Argument("", help="Restrict to this username."),
    fmt: FormatOption = Format.table,
    show: bool = typer.Option(False, "--show", help="Reveal passwords in the table output."),
    clipboard: bool = typer.Option(
        False, "--clipboard", "-c", help="Copy the password to the clipboard, print nothing."
    ),
) -> None:
    """Get password(s) for a URL."""
    try:
        entries = client.get_password(url, username)
    except ApwError as exc:
        fail(exc, fmt)
    if clipboard:
        copy_secret([(e.username, e.password) for e in entries], "password")
        return
    emit(entries, fmt, reveal=show)


@pw_app.command("save")
def pw_save(
    url: str,
    username: str,
    stdin: bool = typer.Option(
        False, "--stdin", help="Read the password from stdin (implied when piped)."
    ),
) -> None:
    """Create or update a password."""
    if stdin or not sys.stdin.isatty():  # piped input can't answer a prompt
        password = sys.stdin.read().strip()
    else:
        password = typer.prompt("Enter password", hide_input=True)
    try:
        client.save_account(url, username, password)
    except ApwError as exc:
        fail(exc)
    status_line("saved")
