"""The `skills` and `mcp` command groups, and the MCP server's tool scoping."""

import asyncio
from pathlib import Path

from typer.testing import CliRunner

from apwcli.cli import app

runner = CliRunner()


def test_skills_list_names_the_bundled_skill() -> None:
    result = runner.invoke(app, ["skills", "list"])
    assert result.exit_code == 0
    assert "apple-passwords" in result.stdout


def test_skills_show_prints_skill_md() -> None:
    result = runner.invoke(app, ["skills", "show"])
    assert result.exit_code == 0
    assert result.stdout.startswith("---")
    assert "apwcli pw" in result.stdout


def test_skills_install_copies_into_directory(tmp_path: Path) -> None:
    result = runner.invoke(app, ["skills", "install", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "apple-passwords" / "SKILL.md").is_file()


def test_skills_show_unknown_name_errors() -> None:
    assert runner.invoke(app, ["skills", "show", "nope"]).exit_code == 2


def test_mcp_install_unknown_client_errors() -> None:
    assert runner.invoke(app, ["mcp", "install", "nope"]).exit_code == 2


def _tool_names(allow_passwords: bool) -> set[str]:
    from apwcli.mcpserver import build_server

    server = build_server(allow_passwords)
    return {tool.name for tool in asyncio.run(server.list_tools())}


def test_mcp_server_hides_passwords_by_default() -> None:
    tools = _tool_names(allow_passwords=False)
    assert {
        "status",
        "start_pairing",
        "submit_pin",
        "get_otp",
        "save_password",
    } <= tools
    assert "get_password" not in tools
    assert "list_accounts" not in tools  # the helper has no account-listing primitive


def test_mcp_server_allow_passwords_opt_in() -> None:
    assert "get_password" in _tool_names(allow_passwords=True)
