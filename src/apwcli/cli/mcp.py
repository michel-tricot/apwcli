"""MCP commands (the `mcp` group): run the server and wire it into clients' configs."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from apwcli.cli.common import console, mcp_app


@mcp_app.command("run")
def mcp_run(
    allow_passwords: bool = typer.Option(
        False,
        "--allow-passwords",
        help="Also expose plaintext password reads (results travel to the model provider).",
    ),
) -> None:
    """Serve Apple Passwords over MCP (stdio). Started by the client, not by hand."""
    from apwcli.mcpserver import run as run_server

    run_server(allow_passwords)


def _apwcli_command() -> str:
    # Prefer the binary we are running from: absolute() (not resolve()) keeps a
    # package manager's stable bin/ symlink out of versioned install dirs.
    exe = Path(sys.argv[0])
    if exe.name == "apwcli" and exe.is_file():
        return str(exe.absolute())
    return shutil.which("apwcli") or "apwcli"


@dataclass(frozen=True)
class Client:
    key: str
    label: str
    config_path: str | None = None  # JSON config to update (relative to home); None: no file edit
    servers_key: str = "mcpServers"
    entry_extra: tuple[tuple[str, str], ...] = ()  # extra fields some clients want
    manual: str | None = None  # instructions when we cannot (or should not) edit config


def _clients() -> list[Client]:
    command = _apwcli_command()
    return [
        Client(
            key="claude-code",
            label="Claude Code",
            manual=f"claude mcp add --scope user apw -- {command} mcp run",
        ),
        Client(
            key="claude-desktop",
            label="Claude Desktop",
            config_path="Library/Application Support/Claude/claude_desktop_config.json",
        ),
        Client(key="cursor", label="Cursor", config_path=".cursor/mcp.json"),
        Client(
            key="vscode",
            label="VS Code (Copilot)",
            config_path="Library/Application Support/Code/User/mcp.json",
            servers_key="servers",
            entry_extra=(("type", "stdio"),),
        ),
        Client(key="windsurf", label="Windsurf", config_path=".codeium/windsurf/mcp_config.json"),
        Client(key="gemini-cli", label="Gemini CLI", config_path=".gemini/settings.json"),
        Client(
            key="zed",
            label="Zed",
            manual=(
                "Add to ~/.config/zed/settings.json:\n"
                '  "context_servers": {\n'
                f'    "apw": {{ "command": {{ "path": "{command}", "args": ["mcp", "run"] }} }}\n'
                "  }"
            ),
        ),
        Client(
            key="codex",
            label="Codex CLI",
            manual=(
                "Add to ~/.codex/config.toml:\n"
                f'  [mcp_servers.apw]\n  command = "{command}"\n  args = ["mcp", "run"]'
            ),
        ),
    ]


def _entry(client: Client) -> dict:
    return dict(client.entry_extra) | {"command": _apwcli_command(), "args": ["mcp", "run"]}


def _install_into_json(client: Client) -> None:
    path = Path.home() / str(client.config_path)
    config: dict = {}
    if path.exists():
        try:
            config = json.loads(path.read_text() or "{}")
        except json.JSONDecodeError as exc:
            console.print(
                f"[red]Error:[/red] could not parse {path} ({exc}); add this entry manually:"
            )
            typer.echo(json.dumps({client.servers_key: {"apw": _entry(client)}}, indent=2))
            raise typer.Exit(1) from None
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    config.setdefault(client.servers_key, {})["apw"] = _entry(client)
    path.write_text(json.dumps(config, indent=2) + "\n")
    console.print(f"Added the 'apw' MCP server to {client.label}: {path}")
    console.print(f"Restart {client.label} to pick it up.")


def _run_claude_code(client: Client) -> None:
    command = _apwcli_command()
    if shutil.which("claude") is None:
        console.print("Claude Code's `claude` CLI is not on PATH; run this once it is:")
        typer.echo(client.manual)
        return
    result = subprocess.run(
        ["claude", "mcp", "add", "--scope", "user", "apw", "--", command, "mcp", "run"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"[red]Error:[/red] `claude mcp add` failed:\n{result.stderr.strip()}")
        raise typer.Exit(1)
    console.print("Added the 'apw' MCP server to Claude Code (user scope).")


def _pick_client(clients: list[Client]) -> Client:
    console.print("Which MCP client should use apwcli?\n")
    for i, c in enumerate(clients, start=1):
        console.print(f"  {i}. {c.label}")
    console.print()
    choice = typer.prompt("Number")
    try:
        return clients[int(choice) - 1]
    except (ValueError, IndexError):
        console.print(f"[red]Error:[/red] pick a number between 1 and {len(clients)}")
        raise typer.Exit(2) from None


@mcp_app.command("install")
def mcp_install(
    client_key: Annotated[
        str | None,
        typer.Argument(
            help="MCP client to configure (claude-code, claude-desktop, cursor, vscode, "
            "windsurf, gemini-cli, zed, codex). Omit to choose interactively."
        ),
    ] = None,
) -> None:
    """Configure an MCP client to use apwcli (updates its config, or shows how)."""
    clients = _clients()
    if client_key is None:
        if not sys.stdin.isatty():
            console.print(
                "[red]Error:[/red] no terminal to ask in; pass a client, "
                "e.g. `apwcli mcp install cursor`"
            )
            raise typer.Exit(2)
        client = _pick_client(clients)
    else:
        match = next((c for c in clients if c.key == client_key.lower()), None)
        if match is None:
            console.print(
                f"[red]Error:[/red] unknown client {client_key!r}; "
                f"one of: {', '.join(c.key for c in clients)}"
            )
            raise typer.Exit(2)
        client = match

    if client.key == "claude-code":
        _run_claude_code(client)
    elif client.config_path is not None:
        _install_into_json(client)
    else:
        console.print(f"To wire apwcli into {client.label}:\n")
        typer.echo(client.manual)
