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


def test_startup_gate_requires_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setattr(sys, "platform", "linux")  # override the macOS-assuming fixture
    result = runner.invoke(app, ["daemon", "status"])
    assert result.exit_code == 1
    assert "requires macOS" in result.stderr


def test_help_and_version_work_off_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setattr(sys, "platform", "linux")  # eager options must bypass the gate
    assert runner.invoke(app, ["--help"]).exit_code == 0
    assert runner.invoke(app, ["--version"]).exit_code == 0


def test_daemon_status_reports_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apwcli.cli.client.daemon.status",
        lambda: {"running": False, "bridge": False, "paired": False},
    )
    result = runner.invoke(app, ["daemon", "status"])
    assert result.exit_code == 9  # INVALID_SESSION
    assert "stopped" in result.stdout


def test_daemon_restart_without_browser_fails_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    # restart must pre-check browsers and fail with a hint, not let _spawn raise uncaught.
    import apwcli.cli.daemon as dm

    monkeypatch.setattr(dm, "installed_browsers", lambda: [])
    result = runner.invoke(app, ["daemon", "restart"])
    assert result.exit_code == 1
    assert "No supported browser found" in result.stderr
    assert result.exception is None or isinstance(result.exception, SystemExit)


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
    monkeypatch.setattr(
        "apwcli.cli.common.subprocess.run", lambda *_a, input, **_k: copied.append(input)
    )
    result = runner.invoke(app, ["pw", "get", "github.com", "-c", "--clear-after", "0"])
    assert result.exit_code == 0
    assert copied == [b"hunter2"]
    assert "hunter2" not in result.stdout
    assert "clipboard" in result.stdout


def test_pw_get_clipboard_schedules_auto_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    from apwlib import PasswordEntry

    entries = [PasswordEntry(username="me@example.com", domain="github.com", password="hunter2")]
    monkeypatch.setattr("apwcli.cli.client.get_password", lambda _url, _login="": entries)
    monkeypatch.setattr("apwcli.cli.common.subprocess.run", lambda *_a, **_k: None)
    scheduled: list[tuple[bytes, float]] = []
    monkeypatch.setattr(
        "apwcli.cli.common._schedule_clipboard_clear",
        lambda data, secs: scheduled.append((data, secs)),
    )
    result = runner.invoke(app, ["pw", "get", "github.com", "-c"])  # default clear-after
    assert result.exit_code == 0
    assert scheduled == [(b"hunter2", 20)]
    assert "clears in 20s" in result.stdout


def test_clipboard_clear_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from apwlib import PasswordEntry

    entries = [PasswordEntry(username="me@example.com", domain="github.com", password="hunter2")]
    monkeypatch.setattr("apwcli.cli.client.get_password", lambda _url, _login="": entries)
    monkeypatch.setattr("apwcli.cli.common.subprocess.run", lambda *_a, **_k: None)
    scheduled: list = []
    monkeypatch.setattr(
        "apwcli.cli.common._schedule_clipboard_clear", lambda *a: scheduled.append(a)
    )
    result = runner.invoke(app, ["pw", "get", "github.com", "-c", "--clear-after", "0"])
    assert result.exit_code == 0
    assert scheduled == []
    assert "clears in" not in result.stdout


def test_pw_generate_saves_and_shows(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "apwcli.cli.client.save_account", lambda u, user, pw: saved.append((u, user, pw))
    )
    result = runner.invoke(
        app, ["pw", "generate", "example.com", "me@example.com", "-n", "24", "--show"]
    )
    assert result.exit_code == 0
    assert len(saved) == 1 and saved[0][:2] == ("example.com", "me@example.com")
    generated = saved[0][2]
    assert len(generated) == 24
    assert generated in result.stdout  # --show reveals it


def test_pw_generate_does_not_show_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list = []
    monkeypatch.setattr(
        "apwcli.cli.client.save_account", lambda u, user, pw: saved.append((u, user, pw))
    )
    result = runner.invoke(app, ["pw", "generate", "example.com", "me@example.com"])
    assert result.exit_code == 0
    assert saved[0][2] not in result.stdout  # saved, not printed
    assert "not shown" in result.stdout


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
    monkeypatch.setattr(
        "apwcli.cli.common.subprocess.run", lambda *_a, input, **_k: copied.append(input)
    )
    result = runner.invoke(app, ["otp", "get", "github.com", "-c", "--clear-after", "0"])
    assert result.exit_code == 0
    assert copied == [b"123456"]


def test_version_names_both_packages() -> None:
    from apwlib import __version__ as lib_version

    from apwcli import __version__ as cli_version

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"apwcli {cli_version} (apwlib {lib_version})"


def test_pw_save_reads_piped_stdin_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "apwcli.cli.client.save_account", lambda url, user, pw: saved.append((url, user, pw))
    )
    result = runner.invoke(app, ["pw", "save", "example.com", "me@example.com"], input="s3cret\n")
    assert result.exit_code == 0
    assert saved == [("example.com", "me@example.com", "s3cret")]


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


def test_prompt_pin_uses_window_without_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from apwcli.cli.common import _prompt_pin

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("apwlib.pinwindow.request_pin", lambda: "654321")
    assert _prompt_pin() == "654321"


def test_prompt_pin_uses_terminal_with_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from apwcli.cli.common import _prompt_pin

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("typer.prompt", lambda _msg: "111222")
    assert _prompt_pin() == "111222"


def test_generate_password_properties() -> None:
    import re

    from apwcli.cli.passwords import _generate_password

    pw = _generate_password(30, symbols=True)
    assert len(pw) == 30
    assert re.search(r"[a-z]", pw) and re.search(r"[A-Z]", pw)
    assert re.search(r"[0-9]", pw) and re.search(r"[^A-Za-z0-9]", pw)

    plain = _generate_password(16, symbols=False)
    assert len(plain) == 16 and plain.isalnum()

    # Two draws should differ (CSPRNG); vanishingly unlikely to collide.
    assert _generate_password(24, True) != _generate_password(24, True)


def test_clipboard_helper_clears_only_when_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    from apwcli import _clipboard

    calls: list = []

    class _Result:
        def __init__(self, out: bytes) -> None:
            self.stdout = out

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs.get("input")))
        return _Result(b"secret") if argv == ["pbpaste"] else _Result(b"")

    monkeypatch.setattr(_clipboard.subprocess, "run", fake_run)
    assert _clipboard.clear_if_unchanged(b"secret") is True
    assert (["pbcopy"], b"") in calls  # cleared with empty input

    calls.clear()
    monkeypatch.setattr(_clipboard.subprocess, "run", lambda argv, **k: _Result(b"different"))
    assert _clipboard.clear_if_unchanged(b"secret") is False
