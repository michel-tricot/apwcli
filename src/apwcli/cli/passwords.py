"""Password commands (the `pw` group)."""

from __future__ import annotations

import secrets
import string
import sys

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
    pw_app,
    status_line,
)

# Symbols kept shell- and site-safe (no quotes, backslash, or space).
_SYMBOLS = "!@#$%^&*()-_=+[]{}"


def _generate_password(length: int, symbols: bool) -> str:
    """A random password with at least one char from each enabled class (CSPRNG)."""
    classes = [string.ascii_lowercase, string.ascii_uppercase, string.digits]
    if symbols:
        classes.append(_SYMBOLS)
    alphabet = "".join(classes)
    chars = [secrets.choice(c) for c in classes]  # guarantee one of each class
    chars += [secrets.choice(alphabet) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


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
    clear_after: ClearAfterOption = CLIPBOARD_CLEAR_SECONDS,
) -> None:
    """Get password(s) for a URL."""
    try:
        entries = client.get_password(url, username)
    except ApwError as exc:
        fail(exc, fmt)
    if clipboard:
        copy_secret([(e.username, e.password) for e in entries], "password", clear_after)
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


@pw_app.command("generate")
def pw_generate(
    url: str,
    username: str,
    length: int = typer.Option(20, "--length", "-n", min=8, help="Password length."),
    symbols: bool = typer.Option(True, "--symbols/--no-symbols", help="Include symbols."),
    show: bool = typer.Option(False, "--show", help="Print the generated password."),
    clipboard: bool = typer.Option(
        False, "--clipboard", "-c", help="Copy the password to the clipboard instead of saving it."
    ),
    clear_after: ClearAfterOption = CLIPBOARD_CLEAR_SECONDS,
) -> None:
    """Generate a strong password, save it, and (optionally) reveal or copy it."""
    password = _generate_password(length, symbols)
    try:
        client.save_account(url, username, password)
    except ApwError as exc:
        fail(exc)
    status_line("saved")
    if clipboard:
        copy_secret([(username, password)], "password", clear_after)
    elif show:
        typer.echo(password)
    else:
        status_line("password saved but not shown — use --show or -c", ok=True)
