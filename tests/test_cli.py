import pytest
from typer.testing import CliRunner

from apwcli.cli import app

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Apple Passwords" in result.stdout


@pytest.mark.parametrize("group", ["daemon", "pw", "otp"])
def test_subcommand_help(group: str) -> None:
    result = runner.invoke(app, [group, "--help"])
    assert result.exit_code == 0


def test_pair_lives_under_daemon() -> None:
    assert runner.invoke(app, ["daemon", "pair", "--help"]).exit_code == 0
    # not a top-level command
    assert runner.invoke(app, ["pair", "--help"]).exit_code != 0
    assert runner.invoke(app, ["auth", "--help"]).exit_code != 0


def test_daemon_status_reports_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apwcli.cli.client.daemon.status",
        lambda: {"running": False, "bridge": False, "paired": False},
    )
    result = runner.invoke(app, ["daemon", "status"])
    assert result.exit_code == 9  # INVALID_SESSION
    assert "stopped" in result.stdout


def test_daemon_status_shows_daemon_and_pairing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apwcli.cli.client.daemon.status",
        lambda: {"running": True, "bridge": True, "paired": True},
    )
    result = runner.invoke(app, ["daemon", "status"])
    assert result.exit_code == 0
    assert "daemon" in result.stdout and "running" in result.stdout
    assert "pairing" in result.stdout and "paired" in result.stdout


def test_pw_list_text_format_is_tsv(monkeypatch: pytest.MonkeyPatch) -> None:
    from apwlib import PasswordEntry

    entries = [PasswordEntry(username="me@example.com", domain="github.com", password="hunter2")]
    monkeypatch.setattr("apwcli.cli.client.get_login_names", lambda _url: entries)
    result = runner.invoke(app, ["pw", "list", "github.com", "--format", "text"])
    assert result.exit_code == 0
    assert "me@example.com\tgithub.com" in result.stdout


def test_pw_list_json_format(monkeypatch: pytest.MonkeyPatch) -> None:
    from apwlib import PasswordEntry

    entries = [PasswordEntry(username="me@example.com", domain="github.com")]
    monkeypatch.setattr("apwcli.cli.client.get_login_names", lambda _url: entries)
    result = runner.invoke(app, ["pw", "list", "github.com", "--format", "json"])
    assert result.exit_code == 0
    assert '"results"' in result.stdout and "me@example.com" in result.stdout


def test_pw_list_table_omits_empty_password_column(monkeypatch: pytest.MonkeyPatch) -> None:
    from apwlib import PasswordEntry

    entries = [PasswordEntry(username="me@example.com", domain="github.com", password=None)]
    monkeypatch.setattr("apwcli.cli.client.get_login_names", lambda _url: entries)
    result = runner.invoke(app, ["pw", "list", "github.com"])
    assert result.exit_code == 0
    assert "username" in result.stdout
    assert "password" not in result.stdout


def test_pw_get_table_masks_password_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from apwlib import PasswordEntry

    entries = [PasswordEntry(username="me@example.com", domain="github.com", password="hunter2")]
    monkeypatch.setattr("apwcli.cli.client.get_password", lambda _url, _login="": entries)
    result = runner.invoke(app, ["pw", "get", "github.com"])
    assert result.exit_code == 0
    assert "password" in result.stdout
    assert "hunter2" not in result.stdout
    assert "••••" in result.stdout


def test_pw_get_show_reveals_password(monkeypatch: pytest.MonkeyPatch) -> None:
    from apwlib import PasswordEntry

    entries = [PasswordEntry(username="me@example.com", domain="github.com", password="hunter2")]
    monkeypatch.setattr("apwcli.cli.client.get_password", lambda _url, _login="": entries)
    result = runner.invoke(app, ["pw", "get", "github.com", "--show"])
    assert result.exit_code == 0
    assert "hunter2" in result.stdout


def test_pw_get_text_format_is_never_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    from apwlib import PasswordEntry

    entries = [PasswordEntry(username="me@example.com", domain="github.com", password="hunter2")]
    monkeypatch.setattr("apwcli.cli.client.get_password", lambda _url, _login="": entries)
    result = runner.invoke(app, ["pw", "get", "github.com", "--format", "text"])
    assert result.exit_code == 0
    assert "hunter2" in result.stdout


def test_pw_get_clipboard_copies_without_printing(monkeypatch: pytest.MonkeyPatch) -> None:
    from apwlib import PasswordEntry

    entries = [PasswordEntry(username="me@example.com", domain="github.com", password="hunter2")]
    copied: list[bytes] = []
    monkeypatch.setattr("apwcli.cli.client.get_password", lambda _url, _login="": entries)
    monkeypatch.setattr("apwcli.cli.subprocess.run", lambda *_a, input, **_k: copied.append(input))
    result = runner.invoke(app, ["pw", "get", "github.com", "-c"])
    assert result.exit_code == 0
    assert copied == [b"hunter2"]
    assert "hunter2" not in result.stdout
    assert "clipboard" in result.stdout


def test_pw_get_clipboard_refuses_multiple_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    from apwlib import PasswordEntry, Status

    entries = [
        PasswordEntry(username="a@example.com", domain="github.com", password="pw1"),
        PasswordEntry(username="b@example.com", domain="github.com", password="pw2"),
    ]
    monkeypatch.setattr("apwcli.cli.client.get_password", lambda _url, _login="": entries)
    result = runner.invoke(app, ["pw", "get", "github.com", "-c"])
    assert result.exit_code == int(Status.INVALID_PARAM)
    assert "narrow" in result.stderr


def test_otp_get_clipboard_copies_code(monkeypatch: pytest.MonkeyPatch) -> None:
    from apwlib import OTPEntry

    entries = [OTPEntry(username="me@example.com", domain="github.com", code="123456")]
    copied: list[bytes] = []
    monkeypatch.setattr("apwcli.cli.client.get_otp", lambda _url: entries)
    monkeypatch.setattr("apwcli.cli.subprocess.run", lambda *_a, input, **_k: copied.append(input))
    result = runner.invoke(app, ["otp", "get", "github.com", "-c"])
    assert result.exit_code == 0
    assert copied == [b"123456"]


def test_version() -> None:
    from apwcli import __version__

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_pw_list_without_daemon_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from apwlib import DaemonNotRunningError, Status

    def boom(_url: str):
        raise DaemonNotRunningError(Status.INVALID_SESSION)

    monkeypatch.setattr("apwcli.cli.client.get_login_names", boom)
    result = runner.invoke(app, ["pw", "list", "https://github.com"])
    assert result.exit_code == 9


def test_pw_list_not_paired_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    from apwlib import NotPairedError, Status

    def boom(_url: str):
        raise NotPairedError(Status.INVALID_SESSION, "session is not paired")

    monkeypatch.setattr("apwcli.cli.client.get_login_names", boom)
    result = runner.invoke(app, ["pw", "list", "github.com"])
    assert result.exit_code == 9
    assert "apwcli daemon pair" in result.stderr
