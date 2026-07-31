"""`apwcli doctor` diagnostics, with the environment stubbed."""

from __future__ import annotations

from pathlib import Path

import pytest
from apwlib.browsers import Browser
from typer.testing import CliRunner

from apwcli.cli import app

runner = CliRunner()

_BROWSER = Browser(
    id="brave", name="Brave", binary=Path("/x"), data_dir=Path("/x"), brew_cask="brave-browser"
)


def _stub(monkeypatch: pytest.MonkeyPatch, *, browsers, manifest, source, status) -> None:
    monkeypatch.setattr("apwcli.cli.doctor.installed_browsers", lambda: browsers)
    monkeypatch.setattr("apwcli.cli.doctor.find_extension_source", lambda: source)
    monkeypatch.setattr("apwcli.cli.doctor.APPLE_NATIVE_MANIFEST", manifest)
    monkeypatch.setattr("apwcli.cli.client.daemon.status", lambda: status)


def test_doctor_all_green(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = tmp_path / "com.apple.passwordmanager.json"
    manifest.write_text("{}")
    _stub(
        monkeypatch,
        browsers=[_BROWSER],
        manifest=manifest,
        source=Path("/ext/3.3.0_0"),
        status={
            "running": True,
            "bridge": True,
            "paired": True,
            "browser": "Google Chrome",
            "browser_pid": 4242,
        },
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "v3.3.0_0" in result.stdout
    assert "paired" in result.stdout
    assert "Google Chrome (pid 4242)" in result.stdout  # the browser hosting the bridge


def test_doctor_fails_without_browser(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text("{}")
    _stub(
        monkeypatch,
        browsers=[],
        manifest=manifest,
        source=Path("/ext/3.3.0_0"),
        status={"running": False, "bridge": False, "paired": False},
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "none installed" in result.stdout
    assert "brew install" in result.stdout


def test_doctor_fails_without_extension(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text("{}")
    _stub(
        monkeypatch,
        browsers=[_BROWSER],
        manifest=manifest,
        source=None,
        status={"running": False, "bridge": False, "paired": False},
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_doctor_unpaired_is_not_a_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text("{}")
    _stub(
        monkeypatch,
        browsers=[_BROWSER],
        manifest=manifest,
        source=Path("/ext/3.3.0_0"),
        status={"running": True, "bridge": True, "paired": False},
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0  # prerequisites are fine; pairing is on-demand
    assert "not paired" in result.stdout
