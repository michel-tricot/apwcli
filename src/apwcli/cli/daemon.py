"""Daemon lifecycle and pairing commands (the `daemon` group)."""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys

import typer
from apwlib import ApwError, Status
from apwlib.browsers import BROWSERS, installed_browsers
from apwlib.config import read_config, write_config
from apwlib.paths import LOG_PATH

from apwcli.cli.common import _prompt_pin, client, daemon_app, fail, render_status, status_line


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
        fail(ApwError(Status.GENERIC_ERROR, "apwcli requires macOS"))
    if not installed_browsers():
        hints = "\n".join(f"  brew install --cask {b.brew_cask}  # {b.name}" for b in BROWSERS)
        fail(ApwError(Status.GENERIC_ERROR, f"No supported browser found. Install one:\n{hints}"))

    if browser:
        write_config({"browser": browser.lower()})

    if foreground:
        from apwlib.browsers import resolve_browser
        from apwlib.daemon import run

        chosen = resolve_browser(browser or read_config().get("browser"))
        if chosen is None:
            fail(ApwError(Status.INVALID_PARAM, f"Browser not available: {browser}"))
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(run(chosen))
        return

    ready = client.daemon.start()  # spawn detached + wait for the bridge
    render_status(client.daemon.status())
    if not ready:
        fail(
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
    status_line("daemon stopped" if stopped else "no daemon was running", ok=stopped)


@daemon_app.command("restart")
def daemon_restart() -> None:
    """Stop any running daemon and start a fresh one (fixes a wedged daemon)."""
    ready = client.daemon.restart()
    render_status(client.daemon.status())
    if not ready:
        fail(
            ApwError(Status.GENERIC_ERROR, "daemon did not become ready; see ~/.apwlib/daemon.log")
        )


@daemon_app.command("logs")
def daemon_logs(
    lines: int = typer.Option(40, "--lines", "-n", help="Show the last N lines (0 for all)."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream new lines (Ctrl-C to stop)."),
    clear: bool = typer.Option(False, "--clear", help="Truncate the log and exit."),
) -> None:
    """Show the daemon log (~/.apwlib/daemon.log)."""
    if clear:
        if LOG_PATH.exists():
            LOG_PATH.write_text("")
        status_line("log cleared")
        return
    if not LOG_PATH.exists():
        status_line("no daemon log yet", ok=False)
        return
    if follow:
        with contextlib.suppress(KeyboardInterrupt):
            subprocess.run(["tail", "-f", "-n", str(lines or 10), str(LOG_PATH)])
        return
    entries = LOG_PATH.read_text().splitlines()
    for line in entries[-lines:] if lines else entries:
        typer.echo(line)


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
        fail(exc)
    if not paired:
        fail(ApwError(Status.INVALID_SESSION, "pairing failed (wrong PIN?)"))
    status_line("paired")
