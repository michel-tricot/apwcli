"""Agent integration commands: the `skills` and `mcp` groups.

`skills` manages the agent skill bundled as package data (src/apwcli/skills/);
`mcp` runs the FastMCP server and wires it into MCP clients' config files.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

_console = Console()

skills_app = typer.Typer(no_args_is_help=True, help="Manage the bundled agent skill.")
mcp_app = typer.Typer(no_args_is_help=True, help="Serve Apple Passwords to AI apps over MCP.")

DEFAULT_SKILLS_DIR = Path.home() / ".claude" / "skills"


# --- skills -------------------------------------------------------------------
def _skill_dirs() -> dict[str, Path]:
    root = Path(str(files("apwcli") / "skills"))
    return {d.name: d for d in sorted(root.iterdir()) if (d / "SKILL.md").is_file()}


def _description(skill_dir: Path) -> str:
    for line in (skill_dir / "SKILL.md").read_text().splitlines():
        if line.startswith("description:"):
            return line.removeprefix("description:").strip()
    return ""


def _resolve(name: str | None) -> Path:
    skills = _skill_dirs()
    if name is None and len(skills) == 1:
        return next(iter(skills.values()))
    if name in skills:
        return skills[name]
    _console.print(f"[red]Error:[/red] unknown skill {name!r}; available: {', '.join(skills)}")
    raise typer.Exit(2)


@skills_app.command("list")
def skills_list() -> None:
    """List the agent skills bundled with apwcli."""
    for name, skill_dir in _skill_dirs().items():
        typer.echo(f"{name}\t{_description(skill_dir)}")


@skills_app.command("show")
def skills_show(
    name: Annotated[
        str | None, typer.Argument(help="Skill name (optional when only one ships).")
    ] = None,
) -> None:
    """Print a skill's SKILL.md to stdout."""
    typer.echo((_resolve(name) / "SKILL.md").read_text(), nl=False)


@skills_app.command("install")
def skills_install(
    name: Annotated[
        str | None, typer.Argument(help="Skill name (optional when only one ships).")
    ] = None,
    directory: Annotated[
        Path,
        typer.Option(
            "--dir", help="Skills directory to install into (e.g. a project's .claude/skills)."
        ),
    ] = DEFAULT_SKILLS_DIR,
) -> None:
    """Install a skill into an agent's skills directory (overwrites an older copy)."""
    source = _resolve(name)
    target = directory / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    _console.print(f"Installed skill {source.name!r} to {target}")


# --- mcp ----------------------------------------------------------------------
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
            _console.print(
                f"[red]Error:[/red] could not parse {path} ({exc}); add this entry manually:"
            )
            typer.echo(json.dumps({client.servers_key: {"apw": _entry(client)}}, indent=2))
            raise typer.Exit(1) from None
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    config.setdefault(client.servers_key, {})["apw"] = _entry(client)
    path.write_text(json.dumps(config, indent=2) + "\n")
    _console.print(f"Added the 'apw' MCP server to {client.label}: {path}")
    _console.print(f"Restart {client.label} to pick it up.")


def _run_claude_code(client: Client) -> None:
    command = _apwcli_command()
    if shutil.which("claude") is None:
        _console.print("Claude Code's `claude` CLI is not on PATH; run this once it is:")
        typer.echo(client.manual)
        return
    result = subprocess.run(
        ["claude", "mcp", "add", "--scope", "user", "apw", "--", command, "mcp", "run"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _console.print(f"[red]Error:[/red] `claude mcp add` failed:\n{result.stderr.strip()}")
        raise typer.Exit(1)
    _console.print("Added the 'apw' MCP server to Claude Code (user scope).")


def _pick_client(clients: list[Client]) -> Client:
    _console.print("Which MCP client should use apwcli?\n")
    for i, c in enumerate(clients, start=1):
        _console.print(f"  {i}. {c.label}")
    _console.print()
    choice = typer.prompt("Number")
    try:
        return clients[int(choice) - 1]
    except (ValueError, IndexError):
        _console.print(f"[red]Error:[/red] pick a number between 1 and {len(clients)}")
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
            _console.print(
                "[red]Error:[/red] no terminal to ask in; pass a client, "
                "e.g. `apwcli mcp install cursor`"
            )
            raise typer.Exit(2)
        client = _pick_client(clients)
    else:
        match = next((c for c in clients if c.key == client_key.lower()), None)
        if match is None:
            _console.print(
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
        _console.print(f"To wire apwcli into {client.label}:\n")
        typer.echo(client.manual)
