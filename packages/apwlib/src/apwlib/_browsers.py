"""Approved browsers for hosting the extension and the PIN window.

Discovery is chauffeur's job, and its Chromium-family catalog (chrome, chromium,
brave, edge) is exactly the set apwlib supports. chauffeur stays an implementation
detail, though: this module wraps its browser records in apwlib's own
:class:`BrowserInfo` (just ``id``/``name``/``binary``), so a chauffeur upgrade can't
change apwlib's public shape. It also adds apwlib's own decorations: the managed
profile path per browser (:func:`profile_for`) and Homebrew casks for install hints
(``BREW_CASKS``). Shared by the daemon (which manages a headless browser) and the
PIN window (which opens an app-mode window).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from chauffeur import installed_browsers as _chauffeur_installed
from chauffeur.browsers import catalog as _chauffeur_catalog

from apwlib._paths import BROWSER_PROFILE_DIR

__all__ = ["BREW_CASKS", "BROWSERS", "BrowserInfo", "installed_browsers", "profile_for", "resolve_browser"]


@dataclass(frozen=True)
class BrowserInfo:
    """An approved browser: a stable apwlib type independent of chauffeur's records."""

    id: str
    name: str
    binary: Path


# Homebrew casks for install hints, keyed by browser id.
BREW_CASKS = {
    "chrome": "google-chrome",
    "chromium": "ungoogled-chromium",
    "brave": "brave-browser",
    "edge": "microsoft-edge",
}

BROWSERS: list[BrowserInfo] = [BrowserInfo(id=b.id, name=b.name, binary=b.binary) for b in _chauffeur_catalog()]


def installed_browsers() -> list[BrowserInfo]:
    """The approved browsers actually installed, in catalog order."""
    return [BrowserInfo(id=b.id, name=b.name, binary=b.binary) for b in _chauffeur_installed()]


def profile_for(browser: BrowserInfo) -> Path:
    """The managed profile directory the daemon uses for ``browser``."""
    return BROWSER_PROFILE_DIR / browser.id


def resolve_browser(selected: str | None) -> BrowserInfo | None:
    """Resolve a browser id/name (or ``"auto"``) to an installed ``BrowserInfo``.

    ``"auto"`` (or ``None``) picks the first installed browser. Returns ``None`` if the
    request cannot be satisfied (nothing installed, or an unknown id) — unlike
    chauffeur's raising ``resolve_browser``, and matching case-insensitively, which
    is why this thin wrapper exists at all.
    """
    available = installed_browsers()
    choice = (selected or "auto").lower()
    if choice == "auto":
        return available[0] if available else None
    return next((b for b in available if choice in (b.id, b.name.lower())), None)
