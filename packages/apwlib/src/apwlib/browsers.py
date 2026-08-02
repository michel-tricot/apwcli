"""Approved browsers for hosting the extension and the PIN window.

Discovery is chauffeur's job, and its Chromium-family catalog (chrome, chromium,
brave, edge) is exactly the set apwlib supports — so this module re-exports
chauffeur's ``BrowserInfo``/``installed_browsers`` and adds only apwlib's own
decorations: the managed profile path per browser (:func:`profile_for`) and
Homebrew casks for install hints (``BREW_CASKS``). Shared by the daemon (which
manages a headless browser) and the PIN window (which opens an app-mode window).
"""

from __future__ import annotations

from pathlib import Path

from chauffeur import BrowserInfo, installed_browsers
from chauffeur.browsers import catalog

from apwlib.paths import BROWSER_PROFILE_DIR

__all__ = ["BREW_CASKS", "BROWSERS", "BrowserInfo", "installed_browsers", "profile_for", "resolve_browser"]

# Homebrew casks for install hints, keyed by chauffeur's browser ids.
BREW_CASKS = {
    "chrome": "google-chrome",
    "chromium": "ungoogled-chromium",
    "brave": "brave-browser",
    "edge": "microsoft-edge",
}

BROWSERS: list[BrowserInfo] = list(catalog())


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
