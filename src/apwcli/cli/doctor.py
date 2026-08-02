"""`apwcli doctor` — diagnose the setup chain from macOS down to a paired session.

The checks live in ``apwlib.diagnostics``; this module only renders them.
"""

from __future__ import annotations

import dataclasses
import json

import typer
from apwlib.diagnostics import run_checks

from apwcli.cli.common import app, daemon_client, status_line


@app.command("doctor", rich_help_panel="Daemon & pairing")
def doctor(
    as_json: bool = typer.Option(False, "--json", help="Print the checks as JSON."),
) -> None:
    """Check browser, extension, daemon, and pairing; exit non-zero if a prerequisite fails.

    Platform is already gated at CLI startup (macOS-only), so it isn't re-checked here.
    """
    checks = run_checks(daemon_client)
    ok = all(c.ok for c in checks if c.required)
    if as_json:
        typer.echo(json.dumps({"ok": ok, "checks": [dataclasses.asdict(c) for c in checks]}))
    else:
        for check in checks:
            status_line(f"{check.key.replace('_', ' '):12} {check.detail}", check.ok)
            if not check.ok and check.hint:
                typer.echo(f"  ↳ {check.hint}")
    if not ok:
        raise typer.Exit(1)
