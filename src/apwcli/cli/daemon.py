"""Daemon lifecycle and pairing commands (the `daemon` group)."""

from __future__ import annotations

import contextlib
import subprocess

import typer
from apwlib import ApwError, Status
from apwlib.browsers import resolve_browser
from apwlib.config import write_config
from apwlib.paths import LOG_PATH

from apwcli.cli.common import _prompt_pin, client, daemon_app, fail, render_status, status_line


def _require_ready(ready: bool) -> None:
    """Fail if the daemon didn't come up, pointing at the log."""
    if not ready:
        fail(ApwError(Status.GENERIC_ERROR, "daemon did not become ready; see ~/.apwlib/daemon.log"))


@daemon_app.command("start")
def daemon_start(
    browser: str = typer.Option(None, "--browser", "-b", help="Browser to manage (auto, chromium, chrome, brave)."),
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in the foreground instead of detaching."),
) -> None:
    """Start the managed daemon (usually unnecessary — commands auto-start it)."""
    if browser:
        # Validate before persisting: a bad id written to config would make every
        # later start spawn a daemon that dies on startup.
        if resolve_browser(browser.lower()) is None:
            fail(ApwError(Status.INVALID_PARAM, f"browser not available: {browser}"))
        write_config({"browser": browser.lower()})

    if foreground:
        from apwlib.daemon.__main__ import main as run_foreground

        raise typer.Exit(code=run_foreground())

    try:
        ready = client.daemon.start()  # spawn detached + wait for the bridge
    except ApwError as exc:  # e.g. no supported browser installed
        fail(exc)
    render_status(client.daemon.status())
    _require_ready(ready)


@daemon_app.command("status")
def daemon_status() -> None:
    """Report daemon and pairing state."""
    st = client.daemon.status()
    render_status(st)
    # render_status already showed the red dots; exit non-zero for scripts without a
    # second, redundant `error: …` line (hence a bare Exit, not fail()).
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
    try:
        ready = client.daemon.restart()
    except ApwError as exc:  # e.g. no supported browser installed
        fail(exc)
    render_status(client.daemon.status())
    _require_ready(ready)


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
            subprocess.run(["tail", "-f", "-n", str(lines or 10), str(LOG_PATH)], check=False)
        return
    entries = LOG_PATH.read_text().splitlines()
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
        if not client.daemon.status()["running"]:
            status_line("starting the daemon (takes a few seconds)")
        client.daemon.request_challenge()
        status_line("pairing code requested — macOS is displaying it")
        code = pin or _prompt_pin()
        status_line("verifying")
        client.daemon.verify_challenge(code)
        paired = client.daemon.wait_until_paired()
    except ApwError as exc:
        fail(exc)
    if not paired:
        fail(ApwError(Status.INVALID_SESSION, "pairing failed (wrong PIN?)"))
    status_line("paired")
