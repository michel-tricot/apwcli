"""Daemon lifecycle and pairing commands (the `daemon` group)."""

from __future__ import annotations

import contextlib
import json
import subprocess

import typer
from apwlib import ApwError, Status

from apwcli.cli.common import _prompt_pin, daemon_app, daemon_client, fail, render_status, status_line


@daemon_app.command("start")
def daemon_start(
    browser: str = typer.Option(None, "--browser", "-b", help="Browser to manage for this daemon (auto, chromium, chrome, brave, edge)."),
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in the foreground instead of detaching."),
) -> None:
    """Start the managed daemon (usually unnecessary — commands auto-start it)."""
    chosen = browser.lower() if browser else None  # validated by Daemon.start / the daemon itself

    if foreground:
        from apwlib.daemon.__main__ import main as run_foreground

        raise typer.Exit(code=run_foreground([chosen] if chosen else []))

    try:
        daemon_client.start(chosen)  # spawn detached + wait for the bridge
    except ApwError as exc:  # no/unknown browser, already running with -b, or bridge never came up
        fail(exc)
    render_status(daemon_client.status())


@daemon_app.command("status")
def daemon_status(
    as_json: bool = typer.Option(False, "--json", help="Print the status as JSON."),
) -> None:
    """Report daemon and pairing state."""
    st = daemon_client.status()
    if as_json:
        typer.echo(json.dumps(st))
    else:
        render_status(st)
    # render_status already showed the red dots; exit non-zero for scripts without a
    # second, redundant `error: …` line (hence a bare Exit, not fail()).
    if not st["running"]:
        raise typer.Exit(code=int(Status.INVALID_SESSION))


@daemon_app.command("stop")
def daemon_stop() -> None:
    """Stop the running daemon (and its managed browser)."""
    stopped = daemon_client.stop()
    status_line("daemon stopped" if stopped else "no daemon was running", ok=stopped)


@daemon_app.command("restart")
def daemon_restart(
    browser: str = typer.Option(None, "--browser", "-b", help="Browser to manage for this daemon (auto, chromium, chrome, brave, edge)."),
) -> None:
    """Stop any running daemon and start a fresh one (fixes a wedged daemon)."""
    chosen = browser.lower() if browser else None  # validated by Daemon.restart
    try:
        daemon_client.restart(chosen)
    except ApwError as exc:  # no supported browser, or the bridge never came up
        fail(exc)
    render_status(daemon_client.status())


@daemon_app.command("logs")
def daemon_logs(
    lines: int = typer.Option(40, "--lines", "-n", help="Show the last N lines (0 for all)."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream new lines (Ctrl-C to stop)."),
    clear: bool = typer.Option(False, "--clear", help="Truncate the log and exit."),
) -> None:
    """Show the daemon log (~/.apwlib/daemon.log)."""
    log_path = daemon_client.log_path
    if clear:
        if log_path.exists():
            log_path.write_text("")
        status_line("log cleared")
        return
    if not log_path.exists():
        status_line("no daemon log yet", ok=False)
        return
    if follow:
        with contextlib.suppress(KeyboardInterrupt):
            subprocess.run(["tail", "-f", "-n", str(lines or 10), str(log_path)], check=False)
        return
    entries = log_path.read_text().splitlines()
    for line in entries[-lines:] if lines else entries:
        typer.echo(line)


@daemon_app.command("pair")
def daemon_pair(
    pin: str = typer.Option(None, "--pin", help="6-digit PIN (otherwise prompted)."),
) -> None:
    """Pair with Apple Passwords using the macOS PIN."""
    # Narrate each phase: auto-start, the PIN window, and verification can each
    # take seconds to minutes with nothing on screen, which reads as a hang.
    try:
        if not daemon_client.status()["running"]:
            status_line("starting the daemon (takes a few seconds)")
        daemon_client.request_challenge()
        status_line("pairing code requested — macOS is displaying it")
        code = pin or _prompt_pin()
        status_line("verifying")
        paired = daemon_client.verify_challenge(code)
    except ApwError as exc:
        fail(exc)
    if not paired:
        fail(ApwError(Status.INVALID_SESSION, "pairing failed (wrong PIN?)"))
    status_line("paired")
