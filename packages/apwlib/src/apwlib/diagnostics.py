"""Structured health checks over the whole chain: browser → helper → daemon → pairing.

`run_checks` is what backs `apwcli doctor`; it returns data, not text, so any
consumer (CLI, MCP, a script) can render or act on it. A check with `required=True`
is a prerequisite: apwlib cannot work at all while it fails. Non-required checks are
informational (e.g. the daemon being stopped just means the next command auto-starts it).
"""

from __future__ import annotations

from dataclasses import dataclass

from apwlib._browsers import BREW_CASKS, BROWSERS, installed_browsers
from apwlib._client import Daemon
from apwlib._paths import APPLE_NATIVE_MANIFEST, cached_extension_version


@dataclass(frozen=True)
class Check:
    """One diagnostic result. `hint` says how to fix it (empty when ok)."""

    key: str
    ok: bool
    required: bool
    detail: str
    hint: str = ""


def run_checks(daemon: Daemon | None = None) -> list[Check]:
    """Diagnose the setup chain; does not auto-start the daemon."""
    daemon = daemon or Daemon(auto_start=False)
    checks: list[Check] = []

    # 1. A launch-constraint-approved browser to host the extension.
    browsers = installed_browsers()
    casks = ", ".join(f"--cask {BREW_CASKS[b.id]}" for b in BROWSERS)
    checks.append(
        Check(
            "browser",
            ok=bool(browsers),
            required=True,
            detail=", ".join(b.name for b in browsers) if browsers else "none installed",
            hint="" if browsers else f"install one, e.g. brew install {casks}",
        )
    )

    # 2. Apple's native-messaging manifest (points at the keychain helper).
    manifest_ok = APPLE_NATIVE_MANIFEST.is_file()
    checks.append(
        Check(
            "apple_helper",
            ok=manifest_ok,
            required=True,
            detail="installed" if manifest_ok else "not installed",
            hint="" if manifest_ok else "install the iCloud Passwords extension and open that browser once",
        )
    )

    # 3. The iCloud Passwords extension cache. Not a prerequisite: the daemon downloads
    # it from the Chrome Web Store on start (and a cached copy keeps working offline).
    version = cached_extension_version()
    checks.append(
        Check(
            "extension",
            ok=True,
            required=False,
            detail=f"v{version} (downloaded)" if version else "downloads on daemon start",
        )
    )

    # 4. Daemon / bridge / pairing.
    st = daemon.status()
    checks.append(
        Check(
            "daemon",
            ok=st["running"],
            required=False,
            detail="running" if st["running"] else "stopped",
            hint="" if st["running"] else "starts automatically on the next command, or run `apwcli daemon start`",
        )
    )
    if st["running"]:
        bridge_detail = "connected" if st["bridge"] else "disconnected"
        if st["bridge"] and st["browser"]:
            bridge_detail += f" — {st['browser']} (pid {st['browser_pid']})"
        checks.append(
            Check(
                "bridge",
                ok=st["bridge"],
                required=False,
                detail=bridge_detail,
                hint="" if st["bridge"] else "run `apwcli daemon restart`",
            )
        )
        checks.append(
            Check(
                "pairing",
                ok=st["paired"],
                required=False,
                detail="paired" if st["paired"] else "not paired",
                hint="" if st["paired"] else "run `apwcli daemon pair`",
            )
        )
    return checks
