"""apwcli — a command-line interface for Apple Passwords."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import enum
import json
import subprocess
import sys
from typing import Annotated, Any, NoReturn

import typer
from apwlib import ApplePasswords, ApwError, NotPairedError, Status
from apwlib.browsers import BROWSERS, installed_browsers
from apwlib.config import read_config, write_config
from rich import box
from rich.console import Console
from rich.table import Table

from apwcli import __version__
from apwcli.agents import mcp_app, skills_app

_console = Console()

app = typer.Typer(no_args_is_help=True, add_completion=False, help="🔑 A CLI for Apple Passwords.")
daemon_app = typer.Typer(no_args_is_help=True, help="Manage the background daemon and pairing.")
pw_app = typer.Typer(no_args_is_help=True, help="Manage accounts and passwords.")
otp_app = typer.Typer(no_args_is_help=True, help="Read one-time codes.")
app.add_typer(pw_app, name="pw", rich_help_panel="Commands")
app.add_typer(otp_app, name="otp", rich_help_panel="Commands")
app.add_typer(daemon_app, name="daemon", rich_help_panel="Daemon & pairing")
app.add_typer(mcp_app, name="mcp", rich_help_panel="Agents")
app.add_typer(skills_app, name="skills", rich_help_panel="Agents")


def _print_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_print_version, is_eager=True, help="Print the version and exit."
        ),
    ] = False,
) -> None:
    pass


def _prompt_pin() -> str:
    if sys.stdin.isatty():
        return typer.prompt("Enter the PIN shown by macOS")
    from apwlib.pinwindow import request_pin  # no TTY: collect the PIN in a small window

    return request_pin()


# An unpaired command auto-pairs: it pops the macOS PIN dialog and collects the code
# from the terminal — or, without a TTY, from a small on-screen PIN window.
client = ApplePasswords(pin_provider=_prompt_pin)


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


def _status_line(text: str, ok: bool = True) -> None:
    typer.echo(f"{_dot(ok)} {text}")


def render_status(st: dict[str, bool]) -> None:
    """Daemon + pairing status with green/red dots."""
    running, bridge, paired = st["running"], st["bridge"], st.get("paired", False)
    daemon_txt = "running" if running else "stopped"
    ext_txt = ("connected" if bridge else "disconnected") if running else "—"
    paired_txt = ("paired" if paired else "not paired") if (running and bridge) else "—"
    _status_line(f"daemon     {daemon_txt}", running)
    _status_line(f"extension  {ext_txt}", bridge)
    _status_line(f"pairing    {paired_txt}", paired)


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    """Column keys in first-seen order, dropping any empty in every row.

    Keeps `pw list` (no passwords retrieved) from showing an empty password column while
    `pw get` (passwords present) still does.
    """
    keys = list({key: None for row in rows for key in row})
    return [k for k in keys if any(row.get(k) not in (None, "", []) for row in rows)]


def _print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        _console.print("[dim](no results)[/dim]")
        return
    columns = _columns(rows)
    table = Table(box=box.ROUNDED, header_style="bold cyan", border_style="dim")
    for column in columns:
        table.add_column(column.replace("_", " "))
    for row in rows:
        table.add_row(*["" if row.get(c) is None else str(row.get(c)) for c in columns])
    _console.print(table)


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


def _fail(exc: ApwError, fmt: Format | None = None) -> NoReturn:
    msg = str(exc)
    if isinstance(exc, NotPairedError):
        msg += " — run `apwcli daemon pair`"
    if fmt is Format.json:
        typer.echo(json.dumps({"error": msg, "status": int(exc.status), "results": []}), err=True)
    else:
        typer.echo(f"error: {msg}", err=True)
    raise typer.Exit(code=int(exc.status))


def _copy_secret(candidates: list[tuple[str, str | None]], what: str) -> None:
    """Copy a single secret to the macOS clipboard, refusing ambiguity."""
    found = [(user, value) for user, value in candidates if value]
    if not found:
        _fail(ApwError(Status.NO_RESULTS, f"no {what} to copy"))
    if len(found) > 1:
        users = ", ".join(user for user, _ in found)
        _fail(ApwError(Status.INVALID_PARAM, f"multiple matches ({users}) — narrow by username"))
    username, secret = found[0]
    subprocess.run(["pbcopy"], input=secret.encode(), check=True)
    _status_line(f"copied {what} for {username} to the clipboard")


# --- daemon -------------------------------------------------------------------
@daemon_app.command("start")
def daemon_start(
    browser: str = typer.Option(
        None, "--browser", "-b", help="Browser to manage (auto, chromium, chrome, brave)."
    ),
    foreground: bool = typer.Option(
        False, "--foreground", "-f", help="Run in the foreground instead of detaching."
    ),
) -> None:
    """Start the managed daemon (usually unnecessary — commands auto-start it)."""
    if sys.platform != "darwin":
        _fail(ApwError(Status.GENERIC_ERROR, "apwcli requires macOS"))
    if not installed_browsers():
        hints = "\n".join(f"  brew install --cask {b.brew_cask}  # {b.name}" for b in BROWSERS)
        _fail(ApwError(Status.GENERIC_ERROR, f"No supported browser found. Install one:\n{hints}"))

    if browser:
        write_config({"browser": browser.lower()})

    if foreground:
        from apwlib.browsers import resolve_browser
        from apwlib.daemon import run

        chosen = resolve_browser(browser or read_config().get("browser"))
        if chosen is None:
            _fail(ApwError(Status.INVALID_PARAM, f"Browser not available: {browser}"))
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(run(chosen))
        return

    ready = client.daemon.start()  # spawn detached + wait for the bridge
    render_status(client.daemon.status())
    if not ready:
        _fail(
            ApwError(Status.GENERIC_ERROR, "daemon did not become ready; see ~/.apwlib/daemon.log")
        )


@daemon_app.command("status")
def daemon_status() -> None:
    """Report daemon and pairing state."""
    st = client.daemon.status()
    render_status(st)
    if not st["running"]:
        raise typer.Exit(code=int(Status.INVALID_SESSION))


@daemon_app.command("stop")
def daemon_stop() -> None:
    """Stop the running daemon (and its managed browser)."""
    stopped = client.daemon.stop()
    _status_line("daemon stopped" if stopped else "no daemon was running", ok=stopped)


@daemon_app.command("pair")
def daemon_pair(
    pin: str = typer.Option(None, "--pin", help="6-digit PIN (otherwise prompted)."),
) -> None:
    """Pair with Apple Passwords using the macOS PIN."""
    try:
        client.daemon.request_challenge()
        code = pin or _prompt_pin()
        client.daemon.verify_challenge(code)
        paired = client.daemon.wait_until_paired()
    except ApwError as exc:
        _fail(exc)
    if not paired:
        _fail(ApwError(Status.INVALID_SESSION, "pairing failed (wrong PIN?)"))
    _status_line("paired")


# --- passwords ----------------------------------------------------------------
@pw_app.command("list")
def pw_list(url: str, fmt: FormatOption = Format.table) -> None:
    """List accounts saved for a URL."""
    try:
        emit(client.get_login_names(url), fmt)
    except ApwError as exc:
        _fail(exc, fmt)


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
        _fail(exc, fmt)
    if clipboard:
        _copy_secret([(e.username, e.password) for e in entries], "password")
        return
    emit(entries, fmt, reveal=show)


@pw_app.command("save")
def pw_save(
    url: str,
    username: str,
    stdin: bool = typer.Option(False, "--stdin", help="Read the password from stdin."),
) -> None:
    """Create or update a password."""
    password = (
        sys.stdin.read().strip() if stdin else typer.prompt("Enter password", hide_input=True)
    )
    try:
        client.save_account(url, username, password)
    except ApwError as exc:
        _fail(exc)
    _status_line("saved")


# --- one-time codes -----------------------------------------------------------
@otp_app.command("get")
def otp_get(
    url: str,
    fmt: FormatOption = Format.table,
    clipboard: bool = typer.Option(
        False, "--clipboard", "-c", help="Copy the code to the clipboard, print nothing."
    ),
) -> None:
    """Get a one-time code for a URL."""
    try:
        entries = client.get_otp(url)
    except ApwError as exc:
        _fail(exc, fmt)
    if clipboard:
        _copy_secret([(e.username, e.code) for e in entries], "one-time code")
        return
    emit(entries, fmt)


@otp_app.command("list")
def otp_list(url: str, fmt: FormatOption = Format.table) -> None:
    """List available one-time codes for a URL."""
    try:
        emit(client.list_otp(url), fmt)
    except ApwError as exc:
        _fail(exc, fmt)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
