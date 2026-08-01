"""`apwcli doctor` — diagnose the setup chain from macOS down to a paired session."""

from __future__ import annotations

import typer
from apwlib.browsers import BROWSERS, find_extension_source, installed_browsers
from apwlib.paths import APPLE_NATIVE_MANIFEST

from apwcli.cli.common import app, client, status_line


def _line(ok: bool, label: str, detail: str, hint: str = "") -> None:
    status_line(f"{label:12} {detail}", ok)
    if not ok and hint:
        typer.echo(f"  ↳ {hint}")


@app.command("doctor", rich_help_panel="Daemon & pairing")
def doctor() -> None:
    """Check browser, extension, daemon, and pairing; exit non-zero if a prerequisite fails.

    Platform is already gated at CLI startup (macOS-only), so it isn't re-checked here.
    """
    prereqs_ok = True

    # 1. A launch-constraint-approved browser to host the extension.
    browsers = installed_browsers()
    if browsers:
        _line(True, "browser", ", ".join(b.name for b in browsers))
    else:
        prereqs_ok = False
        casks = ", ".join(f"--cask {b.brew_cask}" for b in BROWSERS)
        _line(False, "browser", "none installed", f"install one, e.g. brew install {casks}")

    # 2. Apple's native-messaging manifest (points at the keychain helper).
    manifest_ok = APPLE_NATIVE_MANIFEST.is_file()
    _line(
        manifest_ok,
        "apple helper",
        "installed" if manifest_ok else "not installed",
        "install the iCloud Passwords extension and open that browser once",
    )
    prereqs_ok = prereqs_ok and manifest_ok

    # 3. The installed iCloud Passwords extension (source of the loaded copy).
    source = find_extension_source()
    if source is not None:
        _line(True, "extension", f"v{source.name}")
    else:
        prereqs_ok = False
        _line(
            False,
            "extension",
            "not found",
            "add iCloud Passwords from the Chrome Web Store, then open that browser once",
        )

    # 4. Daemon / bridge / pairing (does not auto-start).
    st = client.daemon.status()
    _line(
        st["running"],
        "daemon",
        "running" if st["running"] else "stopped",
        "starts automatically on the next command, or run `apwcli daemon start`",
    )
    if st["running"]:
        bridge_detail = "connected" if st["bridge"] else "disconnected"
        if st["bridge"] and st.get("browser"):
            bridge_detail += f" — {st['browser']} (pid {st['browser_pid']})"
        _line(st["bridge"], "bridge", bridge_detail, "run `apwcli daemon restart`")
        _line(
            st["paired"],
            "pairing",
            "paired" if st["paired"] else "not paired",
            "run `apwcli daemon pair`",
        )

    if not prereqs_ok:
        raise typer.Exit(1)
