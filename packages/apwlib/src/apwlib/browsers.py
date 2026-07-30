"""Discover installed, launch-constraint-approved browsers and the extension source.

Shared by the daemon (which manages a headless browser) and the PIN window (which
opens an app-mode window). Only Chromium-family browsers are supported as managed
hosts, since we load the extension as an unpacked Chrome extension over the
DevTools protocol.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from apwlib.paths import BROWSER_PROFILE_DIR

# The official iCloud Passwords Chrome extension.
EXTENSION_ID = "pejdijmoenmkgeppbflobdenhhabjlaj"
_BACKGROUND = "background.js"
_HOME = Path(os.path.expanduser("~"))


@dataclass(frozen=True)
class Browser:
    id: str
    name: str
    binary: Path
    data_dir: Path  # where the browser stores profiles/extensions
    brew_cask: str

    @property
    def profile(self) -> Path:
        return BROWSER_PROFILE_DIR / self.id


def _browser(id: str, name: str, app: str, data_subdir: str, brew_cask: str) -> Browser:
    return Browser(
        id=id,
        name=name,
        binary=Path(f"/Applications/{app}.app/Contents/MacOS/{app}"),
        data_dir=_HOME / "Library/Application Support" / data_subdir,
        brew_cask=brew_cask,
    )


BROWSERS: list[Browser] = [
    _browser("chromium", "Ungoogled Chromium", "Chromium", "Chromium", "ungoogled-chromium"),
    _browser("brave", "Brave", "Brave Browser", "BraveSoftware/Brave-Browser", "brave-browser"),
    _browser("edge", "Microsoft Edge", "Microsoft Edge", "Microsoft Edge", "microsoft-edge"),
    _browser("chrome", "Google Chrome", "Google Chrome", "Google/Chrome", "google-chrome"),
]


def installed_browsers() -> list[Browser]:
    return [b for b in BROWSERS if b.binary.exists()]


def resolve_browser(selected: str | None) -> Browser | None:
    """Resolve a browser id/name (or ``"auto"``) to an installed ``Browser``.

    ``"auto"`` (or ``None``) picks the first installed browser. Returns ``None`` if the
    request cannot be satisfied (nothing installed, or an unknown id).
    """
    available = installed_browsers()
    if not available:
        return None
    choice = (selected or "auto").lower()
    if choice == "auto":
        return available[0]
    return next((b for b in available if b.id == choice or b.name.lower() == choice), None)


def _subdirs(path: Path) -> list[Path]:
    try:
        return [p for p in path.iterdir() if p.is_dir()]
    except FileNotFoundError:
        return []


def find_extension_source() -> Path | None:
    """Locate an installed iCloud Passwords extension (highest version) across browsers."""
    best: Path | None = None
    best_version: tuple[int, ...] = ()
    for browser in BROWSERS:
        for profile in _subdirs(browser.data_dir):
            base = profile / "Extensions" / EXTENSION_ID
            for version_dir in _subdirs(base):
                if not (version_dir / _BACKGROUND).exists():
                    continue
                version = tuple(int(p) for p in version_dir.name.split(".")[0:4] if p.isdigit())
                if version > best_version:
                    best, best_version = version_dir, version
    return best
