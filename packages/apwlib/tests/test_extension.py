"""The chauffeur extension spec: pure declaration, bridge patches, pinned cache."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from apwlib import paths
from apwlib.daemon import extension
from chauffeur import build_extension
from chauffeur.extension import ExtensionNotFoundError


def _fake_download(body: str, version: str = "3.3.0"):
    """A ``download_extension`` stand-in writing a minimal extension.

    Mirrors chauffeur's contract: the result is validated and loadable as-is
    (chauffeur strips ``_metadata`` itself).
    """

    def download(extension_id: str, dest: Path, **_kwargs: object) -> Path:
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        (dest / "manifest.json").write_text(
            f'{{"name": "iCloud Passwords", "version": "{version}"}}'
        )
        (dest / "background.js").write_text(body)
        return dest

    return download


def _download_fails(extension_id: str, dest: Path, **_kwargs: object) -> Path:
    raise ExtensionNotFoundError("store unreachable")


@pytest.fixture
def data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the spec's pinned cache (and the version reader) at a temp DATA_DIR."""
    monkeypatch.setattr(extension, "DATA_DIR", tmp_path)
    monkeypatch.setattr(paths, "EXTENSION_DIR", tmp_path / f"{extension.EXTENSION_ID}.src")
    monkeypatch.setattr(extension, "BRIDGE_JS", "// bridge")
    return tmp_path


def test_spec_appends_bridge_after_source(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("chauffeur.extension.download_extension", _fake_download("// pristine\n"))

    built = build_extension(extension.extension_spec(), tmp_path / "build")

    background = (built / "background.js").read_text()
    # The bridge reaches the daemon over chauffeur's worker channel, so nothing is
    # injected — the store source is followed by the appended bridge.
    assert background.index("// pristine") < background.index("// bridge")


def test_spec_pins_cache_where_doctor_looks(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("chauffeur.extension.download_extension", _fake_download("// x\n"))

    build_extension(extension.extension_spec(), tmp_path / "build")

    # The pristine cache landed at EXTENSION_DIR (unpatched), visible to doctor.
    assert "// bridge" not in (paths.EXTENSION_DIR / "background.js").read_text()
    assert paths.cached_extension_version() == "3.3.0"


def test_spec_construction_does_no_io(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("chauffeur.extension.download_extension", _download_fails)
    extension.extension_spec()  # must not raise: the download is deferred to build


def test_spec_keeps_worker_awake_aggressively(data_dir: Path) -> None:
    # The worker holds a live SRP session that collapses within ~5s of dormancy;
    # chauffeur's eviction-safe default (25s) is far too slow for that.
    assert extension.extension_spec().keep_alive == 2.0


def test_cached_extension_version_absent(data_dir: Path) -> None:
    assert paths.cached_extension_version() is None


def test_cached_extension_version_tolerates_non_object_manifest(data_dir: Path) -> None:
    paths.EXTENSION_DIR.mkdir(parents=True)
    (paths.EXTENSION_DIR / "manifest.json").write_text("null")  # valid JSON, wrong shape
    assert paths.cached_extension_version() is None
