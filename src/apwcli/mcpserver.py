"""FastMCP server exposing Apple Passwords to AI apps (`apwcli mcp run`). Stdio only.

Plaintext password reads are NOT exposed unless the server is started with
`--allow-passwords`: MCP clients ship tool results to their model provider, so raw
credentials must not travel by default. One-time codes and saves are always available —
codes expire in seconds, and saving only sends what the agent already has.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from apwlib import ApplePasswords
from fastmcp import FastMCP


def _rows(entries: list[Any]) -> list[dict[str, Any]]:
    return [
        {k: v for k, v in dataclasses.asdict(e).items() if v not in (None, "", [])} for e in entries
    ]


def build_server(allow_passwords: bool = False) -> FastMCP:
    server = FastMCP(
        name="apwcli",
        instructions=(
            "Access the user's Apple Passwords (iCloud Keychain). Every read is keyed to "
            "a site URL. If a call fails with 'not paired', call start_pairing, ask the "
            "user for the 6-digit PIN macOS shows on their screen, then call submit_pin."
        ),
    )
    client = ApplePasswords()

    @server.tool
    def status() -> dict[str, bool]:
        """Daemon, browser-extension, and pairing state."""
        return client.daemon.status()

    @server.tool
    def start_pairing() -> str:
        """Begin pairing: macOS displays a 6-digit PIN on the user's screen."""
        client.daemon.start()
        client.daemon.request_challenge()
        return "macOS is showing a 6-digit PIN. Ask the user for it, then call submit_pin."

    @server.tool
    def submit_pin(pin: str) -> dict[str, bool]:
        """Complete pairing with the PIN the user read from the macOS dialog."""
        client.daemon.verify_challenge(pin)
        return {"paired": client.daemon.wait_until_paired()}

    @server.tool
    def list_accounts(url: str) -> list[dict[str, Any]]:
        """List the accounts saved for a site (usernames only, never passwords)."""
        rows = _rows(client.get_login_names(url))
        for row in rows:
            row.pop("password", None)  # defense in depth; ghost search omits it anyway
        return rows

    @server.tool
    def get_otp(url: str) -> list[dict[str, Any]]:
        """The current one-time code(s) for a site."""
        return _rows(client.get_otp(url))

    @server.tool
    def save_password(url: str, username: str, password: str) -> str:
        """Create or update a credential in Apple Passwords."""
        client.save_account(url, username, password)
        return "saved"

    if allow_passwords:

        @server.tool
        def get_password(url: str, username: str = "") -> list[dict[str, Any]]:
            """Plaintext password(s) for a site (enabled by --allow-passwords)."""
            return _rows(client.get_password(url, username))

    return server


def run(allow_passwords: bool = False) -> None:
    build_server(allow_passwords).run()
