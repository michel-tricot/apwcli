"""`apwcli doctor` diagnostics, with the environment stubbed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from apwlib.browsers import BrowserInfo
from typer.testing import CliRunner

from apwcli.cli import app

runner = CliRunner()

_BROWSER = BrowserInfo(id="brave", name="Brave", binary=Path("/x"))


def _stub(monkeypatch: pytest.MonkeyPatch, *, browsers, manifest, version, status) -> None:
    monkeypatch.setattr("apwlib.diagnostics.installed_browsers", lambda: browsers)
    monkeypatch.setattr("apwlib.diagnostics.cached_extension_version", lambda: version)
    monkeypatch.setattr("apwlib.diagnostics.APPLE_NATIVE_MANIFEST", manifest)
    monkeypatch.setattr("apwcli.cli.common.daemon_client.status", lambda: status)


def test_doctor_all_green(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = tmp_path / "com.apple.passwordmanager.json"
    manifest.write_text("{}")
    _stub(
        monkeypatch,
        browsers=[_BROWSER],
        manifest=manifest,
        version="3.3.0",
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
    assert "v3.3.0 (downloaded)" in result.stdout
    assert "paired" in result.stdout
    assert "Google Chrome (pid 4242)" in result.stdout  # the browser hosting the bridge


def test_doctor_fails_without_browser(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text("{}")
    _stub(
        monkeypatch,
        browsers=[],
        manifest=manifest,
        version="3.3.0",
        status={"running": False, "bridge": False, "paired": False, "browser": None, "browser_pid": None},
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "none installed" in result.stdout
    assert "brew install" in result.stdout


def test_doctor_extension_not_cached_is_not_a_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text("{}")
    _stub(
        monkeypatch,
        browsers=[_BROWSER],
        manifest=manifest,
        version=None,
        status={"running": False, "bridge": False, "paired": False, "browser": None, "browser_pid": None},
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0  # the daemon downloads it from the store on start
    assert "downloads on daemon start" in result.stdout


def test_doctor_unpaired_is_not_a_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text("{}")
    _stub(
        monkeypatch,
        browsers=[_BROWSER],
        manifest=manifest,
        version="3.3.0",
        status={"running": True, "bridge": True, "paired": False, "browser": "Brave", "browser_pid": 7},
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0  # prerequisites are fine; pairing is on-demand
    assert "not paired" in result.stdout


def test_doctor_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"  # absent -> apple_helper check fails
    _stub(
        monkeypatch,
        browsers=[_BROWSER],
        manifest=manifest,
        version=None,
        status={"running": False, "bridge": False, "paired": False, "browser": None, "browser_pid": None},
    )
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1  # a required check failed; JSON says which
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    by_key = {c["key"]: c for c in payload["checks"]}
    assert by_key["browser"]["ok"] is True
    assert by_key["apple_helper"]["ok"] is False and by_key["apple_helper"]["required"] is True
    assert by_key["apple_helper"]["hint"]
