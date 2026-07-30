"""build_extension: first copy, version-change refresh, and missing-source handling."""

from __future__ import annotations

from pathlib import Path

import pytest
from apwlib import ApwError
from apwlib.daemon import extension


def _make_source(root: Path, version: str, body: str = "// pristine\n") -> Path:
    """Create a fake installed-extension version dir with a background.js."""
    version_dir = root / version
    version_dir.mkdir(parents=True)
    (version_dir / "background.js").write_text(body)
    (version_dir / "manifest.json").write_text("{}")
    return version_dir


@pytest.fixture
def ext_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    target = tmp_path / "extension"
    monkeypatch.setattr(extension, "EXTENSION_DIR", target)
    monkeypatch.setattr(extension, "BRIDGE_JS", "// bridge")
    monkeypatch.setattr(extension, "ensure_data_dir", lambda: tmp_path)
    return target


def test_first_build_copies_source(
    ext_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _make_source(tmp_path / "v1", "3.1.0_0")
    monkeypatch.setattr(extension, "find_extension_source", lambda: source)

    extension.build_extension(1234, "tok")

    built = (ext_dir / "background.js").read_text()
    assert "// pristine" in built and "APW_CONFIG" in built and "// bridge" in built
    assert (ext_dir / ".source").read_text() == str(source)


def test_rebuilds_when_version_changes(
    ext_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    v1 = _make_source(tmp_path / "a", "3.1.0_0", "// v1\n")
    monkeypatch.setattr(extension, "find_extension_source", lambda: v1)
    extension.build_extension(1, "t")
    assert "// v1" in (ext_dir / "background.js.orig").read_text()

    v2 = _make_source(tmp_path / "b", "3.2.0_0", "// v2\n")
    monkeypatch.setattr(extension, "find_extension_source", lambda: v2)
    extension.build_extension(2, "t")

    assert "// v2" in (ext_dir / "background.js.orig").read_text()
    assert (ext_dir / ".source").read_text() == str(v2)


def test_keeps_cached_copy_when_version_unchanged(
    ext_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _make_source(tmp_path / "v", "3.1.0_0", "// original\n")
    monkeypatch.setattr(extension, "find_extension_source", lambda: source)
    extension.build_extension(1, "t")

    # Same version reported again, but the on-disk source now differs: must NOT re-copy.
    (source / "background.js").write_text("// changed on disk\n")
    extension.build_extension(2, "t")
    assert "// original" in (ext_dir / "background.js.orig").read_text()


def test_keeps_cached_copy_when_source_missing(
    ext_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _make_source(tmp_path / "v", "3.1.0_0")
    monkeypatch.setattr(extension, "find_extension_source", lambda: source)
    extension.build_extension(1, "t")

    monkeypatch.setattr(extension, "find_extension_source", lambda: None)  # install vanished
    extension.build_extension(2, "t")  # must not raise; reuses the cache
    assert (ext_dir / "background.js").read_text().count("APW_CONFIG") == 1


def test_raises_when_no_source_and_no_cache(ext_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extension, "find_extension_source", lambda: None)
    with pytest.raises(ApwError, match="not found"):
        extension.build_extension(1, "t")
