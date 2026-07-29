import pytest

from apwcli.cli import main


def test_greet_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["greet", "world"]) == 0
    assert capsys.readouterr().out == "Hello, world!\n"


def test_greet_empty_name_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["greet", "   "]) == 1
    assert "must not be empty" in capsys.readouterr().err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.startswith("apwcli ")


def test_no_command_fails() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
