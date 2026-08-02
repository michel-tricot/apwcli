"""Shared Typer apps, output rendering, and helpers for the CLI commands."""

from __future__ import annotations

import contextlib
import dataclasses
import enum
import faulthandler
import json
import signal
import subprocess
import sys
from collections.abc import Mapping
from typing import Annotated, Any, NoReturn

import typer
from apwlib import ApplePasswords, ApwError, Daemon, NotPairedError, Status
from apwlib import __version__ as _apwlib_version
from rich import box
from rich.console import Console
from rich.table import Table

from apwcli import __version__

console = Console()

# Escape hatch for a hung command: `kill -USR1 <pid>` dumps every thread's stack
# to stderr, so "it's stuck" becomes "it's stuck HERE". No-op on platforms
# without SIGUSR1 or in embedded interpreters that reject the handler.
with contextlib.suppress(AttributeError, ValueError, OSError):
    faulthandler.register(signal.SIGUSR1)

app = typer.Typer(no_args_is_help=True, add_completion=False, help="🔑 A CLI for Apple Passwords.")
daemon_app = typer.Typer(no_args_is_help=True, help="Manage the background daemon and pairing.")
pw_app = typer.Typer(no_args_is_help=True, help="Manage accounts and passwords.")
otp_app = typer.Typer(no_args_is_help=True, help="Read one-time codes.")
skills_app = typer.Typer(no_args_is_help=True, help="Manage the bundled agent skill.")
mcp_app = typer.Typer(no_args_is_help=True, help="Serve Apple Passwords to AI apps over MCP.")
app.add_typer(pw_app, name="pw", rich_help_panel="Commands")
app.add_typer(otp_app, name="otp", rich_help_panel="Commands")
app.add_typer(daemon_app, name="daemon", rich_help_panel="Daemon & pairing")
app.add_typer(mcp_app, name="mcp", rich_help_panel="Agents")
app.add_typer(skills_app, name="skills", rich_help_panel="Agents")


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"apwcli {__version__} (apwlib {_apwlib_version})")
        raise typer.Exit()


@app.callback()
def _root(
    _version: Annotated[
        bool,
        typer.Option("--version", callback=_print_version, is_eager=True, help="Print the version and exit."),
    ] = False,
) -> None:
    # One platform gate for the whole CLI: every command needs the macOS-only Apple
    # Passwords helper. (--version/--help are eager and exit before this runs.)
    if sys.platform != "darwin":
        fail(ApwError(Status.GENERIC_ERROR, "apwcli requires macOS"))


def _prompt_pin() -> str:
    if sys.stdin.isatty():
        return typer.prompt("Enter the PIN shown by macOS")
    from apwlib.pinwindow import request_pin  # no TTY: collect the PIN in a small window

    status_line("opening a PIN window — enter the code macOS is showing")
    return request_pin()


# An unpaired command auto-pairs: it pops the macOS PIN dialog and collects the code
# from the terminal — or, without a TTY, from a small on-screen PIN window.
client = ApplePasswords(pin_provider=_prompt_pin)

# Explicit daemon control for the `daemon` group, doctor, and pairing; data commands
# go through `client`, which manages its own daemon connection.
daemon_client = Daemon()


class Format(enum.StrEnum):
    text = "text"
    json = "json"
    table = "table"


# --format applies only to commands that return password/OTP data:
# text (pipe-friendly TSV), json (for agents), table (pretty, default).
FormatOption = Annotated[
    Format,
    typer.Option("--format", "-o", help="Output format: text, json, or table."),
]


# --- rendering ---------------------------------------------------------------
def _dot(ok: bool) -> str:
    # click.echo strips ANSI when output isn't a TTY, so pipes stay clean.
    return typer.style("●", fg=typer.colors.GREEN if ok else typer.colors.RED)


def status_line(text: str, ok: bool = True) -> None:
    typer.echo(f"{_dot(ok)} {text}")


def render_status(st: Mapping[str, object]) -> None:
    """Daemon + pairing status with green/red dots."""
    running, bridge, paired = bool(st["running"]), bool(st["bridge"]), bool(st.get("paired"))
    daemon_txt = "running" if running else "stopped"
    ext_txt = ("connected" if bridge else "disconnected") if running else "—"
    paired_txt = ("paired" if paired else "not paired") if (running and bridge) else "—"
    status_line(f"daemon     {daemon_txt}", running)
    status_line(f"extension  {ext_txt}", bridge)
    status_line(f"pairing    {paired_txt}", paired)


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    """Column keys in first-seen order, dropping any empty in every row.

    Keeps `otp list` (no codes retrieved) from showing an empty code column while
    `otp get` (codes present) still does.
    """
    keys = list({key: None for row in rows for key in row})
    return [k for k in keys if any(row.get(k) not in (None, "", []) for row in rows)]


def _print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[dim](no results)[/dim]")
        return
    columns = _columns(rows)
    table = Table(box=box.ROUNDED, header_style="bold cyan", border_style="dim")
    for column in columns:
        table.add_column(column.replace("_", " "))
    for row in rows:
        table.add_row(*["" if row.get(c) is None else str(row.get(c)) for c in columns])
    console.print(table)


_MASK = "••••••••"


def emit(entries: list[Any], fmt: Format, reveal: bool = True) -> None:
    """Render password/OTP results in the chosen format.

    Tables are for human eyes (and terminal scrollback), so passwords are masked there
    unless ``reveal``; `text` and `json` are for pipes and always carry the real values.
    """
    rows = [dataclasses.asdict(e) for e in entries]
    if fmt is Format.table and not reveal:
        rows = [{**row, "password": _MASK} if row.get("password") else row for row in rows]
    if fmt is Format.json:
        compact = [{k: v for k, v in row.items() if v not in (None, [], "")} for row in rows]
        typer.echo(json.dumps({"results": compact, "status": int(Status.SUCCESS)}))
        return
    if fmt is Format.text:
        columns = _columns(rows)
        for row in rows:
            typer.echo("\t".join("" if row.get(c) is None else str(row.get(c)) for c in columns))
        return
    _print_table(rows)


def fail(exc: ApwError, fmt: Format | None = None) -> NoReturn:
    msg = str(exc)
    if isinstance(exc, NotPairedError):
        msg += " — run `apwcli daemon pair`"
    if fmt is Format.json:
        typer.echo(json.dumps({"error": msg, "status": int(exc.status), "results": []}), err=True)
    else:
        typer.echo(f"error: {msg}", err=True)
    raise typer.Exit(code=int(exc.status))


CLIPBOARD_CLEAR_SECONDS = 20  # default lifetime of a secret on the clipboard


def _schedule_clipboard_clear(data: bytes, seconds: float) -> None:
    """Spawn a detached helper that clears the clipboard after ``seconds`` (if unchanged)."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "apwcli._clipboard", str(seconds)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # outlive this process
    )
    if proc.stdin is not None:
        proc.stdin.write(data)  # over stdin, never argv/env (which show up in `ps`)
        proc.stdin.close()


def copy_secret(
    candidates: list[tuple[str, str | None]],
    what: str,
    clear_after: float = CLIPBOARD_CLEAR_SECONDS,
) -> None:
    """Copy a single secret to the macOS clipboard, refusing ambiguity.

    Unless ``clear_after`` is 0, the clipboard is wiped after that many seconds (only if
    it still holds the copied value), so a password doesn't linger indefinitely.
    """
    found = [(user, value) for user, value in candidates if value]
    if not found:
        fail(ApwError(Status.NO_RESULTS, f"no {what} to copy"))
    if len(found) > 1:
        users = ", ".join(user for user, _ in found)
        fail(ApwError(Status.INVALID_PARAM, f"multiple matches ({users}) — narrow by username"))
    username, secret = found[0]
    data = secret.encode()
    subprocess.run(["pbcopy"], input=data, check=True)
    message = f"copied {what} for {username} to the clipboard"
    if clear_after and clear_after > 0:
        _schedule_clipboard_clear(data, clear_after)
        message += f" (clears in {int(clear_after)}s)"
    status_line(message)


ClearAfterOption = Annotated[
    int,
    typer.Option(
        "--clear-after",
        help=f"Seconds before the clipboard is cleared ({CLIPBOARD_CLEAR_SECONDS}; 0 to keep).",
    ),
]
