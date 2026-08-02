"""Collect the pairing PIN in a small browser window when there is no terminal.

The PIN macOS displays must be typed by a human, but callers often run without a
TTY (agents, GUI apps, scripts). Whoever can read the macOS PIN dialog is at the
screen, so instead of a terminal prompt we pop a dialog-sized chromeless window
(an approved browser in ``--app`` mode, driven by chauffeur) showing six code
boxes. The page posts the PIN back over chauffeur's ``py_chauffeur`` channel (or an
empty PIN when it is closed unanswered), and :func:`request_pin` returns it — a
drop-in ``pin_provider`` for the facade::

    pw = ApplePasswords(pin_provider=request_pin)

The page is ``page.html`` next to this module; its look comes from a
stylesheet resolved in order: the ``css`` argument, a user override at
``~/.apwlib/pinwindow.css``, then the bundled ``default.css``.
"""

from __future__ import annotations

import subprocess
import tempfile
import threading
from pathlib import Path

from chauffeur import LaunchError, LaunchSpec, SyncBrowser, Window

from apwlib.browsers import BrowserInfo, installed_browsers, resolve_browser
from apwlib.config import read_config
from apwlib.errors import NotPairedError
from apwlib.paths import BROWSER_PROFILE_DIR, PIN_STYLE_PATH
from apwlib.protocol import Status

_TIMEOUT = 120.0  # seconds a human gets to read the macOS dialog and type the PIN
_WINDOW_SIZE = (390, 320)
_PROFILE_PREFIX = "apwlib-pin-"
_ASSETS = Path(__file__).parent


def _page() -> str:
    return (_ASSETS / "page.html").read_text()


def _style(css: str | None) -> str:
    """The stylesheet to serve: explicit ``css``, the user override file, or the default."""
    if css is not None:
        return css
    if PIN_STYLE_PATH.exists():
        return PIN_STYLE_PATH.read_text()
    return (_ASSETS / "default.css").read_text()


def _running_browser() -> BrowserInfo | None:
    """The installed browser the user is actually running, if any.

    Matches main browser processes only, ignoring our own managed instances (the
    daemon's headless browser and PIN windows), which run with profiles of ours.
    """
    try:
        processes = subprocess.run(["ps", "-axo", "args"], capture_output=True, text=True, check=True).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return None

    def is_user_run(line: str, browser: BrowserInfo) -> bool:
        return line.startswith(str(browser.binary)) and str(BROWSER_PROFILE_DIR) not in line and _PROFILE_PREFIX not in line

    return next(
        (b for b in installed_browsers() if any(is_user_run(line, b) for line in processes)),
        None,
    )


def _window_spec(browser: BrowserInfo, workdir: Path) -> LaunchSpec:
    """A chromeless, dialog-sized app window serving the PIN page from ``workdir``."""
    return LaunchSpec(
        profile=workdir / "profile",
        browser=browser.binary,
        headless=False,
        url=workdir / "page.html",  # app defaults True: a chromeless (--app) window
        window=Window(size=_WINDOW_SIZE, position="top"),  # top of screen, by the macOS PIN dialog
    )


def request_pin(timeout: float = _TIMEOUT, css: str | None = None) -> str:
    """Pop the PIN window and return the six digits the user typed.

    ``css`` replaces the window's stylesheet (falling back to
    ``~/.apwlib/pinwindow.css``, then the bundled default). Raises
    ``NotPairedError`` when no supported browser is installed, the window is
    closed without a code, or nobody answers within ``timeout``.
    """
    # Prefer the browser the user is running, so the window matches what they use.
    browser = _running_browser() or resolve_browser(read_config().get("browser"))
    if browser is None:
        raise NotPairedError(Status.INVALID_SESSION, "no supported browser for the PIN window")

    with tempfile.TemporaryDirectory(prefix=_PROFILE_PREFIX) as tmp:
        workdir = Path(tmp)
        (workdir / "page.html").write_text(_page())
        (workdir / "style.css").write_text(_style(css))

        window = SyncBrowser(_window_spec(browser, workdir))
        answered = threading.Event()
        # Each source records (kind, pin) in ONE atomic write and the first writer
        # wins (a close beacon may race a submit, the timer may race both; sources
        # run on different threads, so the record must not be split across two
        # operations). No outcome recorded means serve() returned on its own —
        # the window was closed.
        outcome: dict[str, tuple[str, str]] = {}

        def _finish(kind: str, pin: str = "") -> None:
            outcome.setdefault("result", (kind, pin))
            answered.set()

        @window.command("pin")
        def _receive(params: dict) -> None:
            _finish("pin", str(params.get("pin", "")))

        timer = threading.Timer(timeout, lambda: _finish("timeout"))
        # Started before the launch: the window is already on screen while start()
        # wires up its channel, so the clock must cover that stretch too — a stall
        # there would otherwise hang with the window showing and no timeout running.
        timer.start()
        try:
            with window:
                window.serve(until=answered)
                # Cancel before the (potentially slow) window teardown in __exit__,
                # so a just-closed window isn't misreported as a timeout.
                timer.cancel()
        except LaunchError as exc:
            raise NotPairedError(Status.INVALID_SESSION, f"PIN window failed to open: {exc}") from exc
        finally:
            timer.cancel()

    match outcome.get("result"):
        case ("pin", pin) if pin:
            return pin
        case ("pin", _):
            raise NotPairedError(Status.INVALID_SESSION, "pairing cancelled")
        case ("timeout", _):
            raise NotPairedError(Status.INVALID_SESSION, "timed out waiting for the PIN")
        case _:  # serve() returned on its own: the window went away unanswered
            raise NotPairedError(Status.INVALID_SESSION, "PIN window closed before a code was entered")
