"""Approved browsers for hosting the extension and the PIN window.

Discovery is chauffeur's job; this module narrows its Chromium-family catalog to what
apwlib supports and decorates each entry with our own bits: the managed profile path
and a Homebrew cask for install hints. Shared by the daemon (which manages a headless
browser) and the PIN window (which opens an app-mode window).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from chauffeur.browsers import catalog

from apwlib.paths import BROWSER_PROFILE_DIR

_BREW_CASKS = {
    "chrome": "google-chrome",
    "chromium": "ungoogled-chromium",
    "brave": "brave-browser",
    "edge": "microsoft-edge",
}


@dataclass(frozen=True)
class Browser:
    id: str
    name: str
    binary: Path
    brew_cask: str

    @property
    def profile(self) -> Path:
        return BROWSER_PROFILE_DIR / self.id


BROWSERS: list[Browser] = [
    Browser(id=b.id, name=b.name, binary=b.binary, brew_cask=_BREW_CASKS[b.id])
    for b in catalog()
    if b.id in _BREW_CASKS
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
