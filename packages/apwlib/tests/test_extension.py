"""The extension cache (store download) and the chauffeur spec carrying the bridge."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from apwlib import ApwError
from apwlib.daemon import extension
from chauffeur import build_extension
from chauffeur.extension import ExtensionNotFoundError


def _fake_download(body: str, version: str = "3.3.0"):
    """A ``download_extension`` stand-in writing a minimal store-shaped extension."""

    def download(extension_id: str, dest: Path, **_kwargs: object) -> Path:
        if dest.exists():
            shutil.rmtree(dest)
        (dest / "_metadata").mkdir(parents=True)
        (dest / "_metadata" / "verified_contents.json").write_text("{}")
        (dest / "manifest.json").write_text(
            f'{{"name": "iCloud Passwords", "version": "{version}"}}'
        )
        (dest / "background.js").write_text(body)
        return dest

    return download


def _download_fails(extension_id: str, dest: Path, **_kwargs: object) -> Path:
    raise ExtensionNotFoundError("store unreachable")


@pytest.fixture
def ext_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    target = tmp_path / "extension"
    monkeypatch.setattr(extension, "EXTENSION_DIR", target)
    monkeypatch.setattr(extension, "BRIDGE_JS", "// bridge")
    monkeypatch.setattr(extension, "ensure_data_dir", lambda: tmp_path)
    return target


def test_downloads_and_strips_metadata(ext_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extension, "download_extension", _fake_download("// pristine\n"))

    assert extension._pristine_extension() == ext_dir
    assert "// pristine" in (ext_dir / "background.js").read_text()
    # Chrome refuses to load an unpacked extension containing _metadata.
    assert not (ext_dir / "_metadata").exists()


def test_refreshes_cache_on_each_start(ext_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extension, "download_extension", _fake_download("// v1\n", "3.1.0"))
    extension._pristine_extension()

    monkeypatch.setattr(extension, "download_extension", _fake_download("// v2\n", "3.2.0"))
    extension._pristine_extension()

    assert "// v2" in (ext_dir / "background.js").read_text()
    assert extension.cached_extension_version() == "3.2.0"


def test_keeps_cache_when_store_unreachable(ext_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extension, "download_extension", _fake_download("// cached\n"))
    extension._pristine_extension()

    monkeypatch.setattr(extension, "download_extension", _download_fails)  # e.g. offline
    assert extension._pristine_extension() == ext_dir  # must not raise; reuses the cache
    assert "// cached" in (ext_dir / "background.js").read_text()


def test_raises_when_no_cache_and_no_store(ext_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extension, "download_extension", _download_fails)
    with pytest.raises(ApwError, match="download"):
        extension._pristine_extension()


def test_spec_builds_config_then_source_then_bridge(
    ext_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(extension, "download_extension", _fake_download("// pristine\n"))

    built = build_extension(extension.extension_spec(4321, "tok"), tmp_path / "build")

    background = (built / "background.js").read_text()
    assert '"port": 4321' in background and '"token": "tok"' in background
    config = background.index("__chauffeur_config")
    assert config < background.index("// pristine") < background.index("// bridge")
    # The cached copy stays pristine; patches land only in the build.
    assert "__chauffeur_config" not in (ext_dir / "background.js").read_text()


def test_cached_extension_version_absent(ext_dir: Path) -> None:
    assert extension.cached_extension_version() is None
