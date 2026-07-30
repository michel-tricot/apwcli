"""Typer CLI for Apple Passwords, one module per command group."""

from apwcli.cli import daemon, mcp, otp, passwords, skills  # noqa: F401  # command registration
from apwcli.cli.common import app, client

__all__ = ["app", "client", "main"]


def main() -> None:
    app()
