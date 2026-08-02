"""The chauffeur extension spec: pure declaration, bridge patches, pinned cache."""

from __future__ import annotations

import json
import re
import shutil
from importlib.resources import files
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
        (dest / "manifest.json").write_text(f'{{"name": "iCloud Passwords", "version": "{version}"}}')
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


def test_spec_appends_bridge_after_source(data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("chauffeur.extension.download_extension", _fake_download("// pristine\n"))

    built = build_extension(extension.extension_spec(), tmp_path / "build")

    background = (built / "background.js").read_text()
    # Layout: injected wire constants, then the store source, then the appended
    # bridge — the config global must exist before either of the others runs.
    assert background.index("__chauffeur_config") < background.index("// pristine") < background.index("// bridge")


def test_bridge_reads_only_injected_config_keys(data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # bridge.js reads globalThis.__chauffeur_config.<key> for every wire constant;
    # a key it references but extension_spec doesn't inject would boot the bridge
    # with undefined constants. Guard the one remaining cross-language coupling.
    from apwlib.protocol import WIRE_UNPAIRED

    monkeypatch.setattr("chauffeur.extension.download_extension", _fake_download("// pristine\n"))
    built = build_extension(extension.extension_spec(), tmp_path / "build")

    background = (built / "background.js").read_text()
    match = re.search(r"globalThis\.__chauffeur_config = (\{.*?\});", background)
    assert match, "inject_config global not found in the built background"
    injected = json.loads(match.group(1))

    bridge = files("apwlib.daemon").joinpath("bridge.js").read_text()  # the real bridge, not the fixture stub
    referenced = set(re.findall(r"CONFIG\.(\w+)", bridge))
    assert referenced and referenced <= set(injected)
    assert injected["wireUnpaired"] == WIRE_UNPAIRED


def test_spec_pins_cache_where_doctor_looks(data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("chauffeur.extension.download_extension", _fake_download("// x\n"))

    build_extension(extension.extension_spec(), tmp_path / "build")

    # The pristine cache landed at EXTENSION_DIR (unpatched), visible to doctor.
    assert "// bridge" not in (paths.EXTENSION_DIR / "background.js").read_text()
    assert paths.cached_extension_version() == "3.3.0"


def test_spec_construction_does_no_io(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("chauffeur.extension.download_extension", _download_fails)
    extension.extension_spec()  # must not raise: the download is deferred to build


def test_cached_extension_version_absent(data_dir: Path) -> None:
    assert paths.cached_extension_version() is None


def test_cached_extension_version_tolerates_non_object_manifest(data_dir: Path) -> None:
    paths.EXTENSION_DIR.mkdir(parents=True)
    (paths.EXTENSION_DIR / "manifest.json").write_text("null")  # valid JSON, wrong shape
    assert paths.cached_extension_version() is None
