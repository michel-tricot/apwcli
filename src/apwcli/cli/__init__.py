"""Typer CLI for Apple Passwords, one module per command group."""

from apwcli.cli import (  # noqa: F401  # command registration
    daemon,
    doctor,
    mcp,
    otp,
    passwords,
    skills,
)
from apwcli.cli.common import app, client

__all__ = ["app", "client", "main"]


def main() -> None:
    app()
