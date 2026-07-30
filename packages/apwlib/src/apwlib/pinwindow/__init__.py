"""Collect the pairing PIN in a small browser window when there is no terminal.

The PIN macOS displays must be typed by a human, but callers often run without a
TTY (agents, GUI apps, scripts). Whoever can read the macOS PIN dialog is at the
screen, so instead of a terminal prompt we pop a dialog-sized chromeless window
(an approved browser in ``--app`` mode) showing six code boxes, served from a
localhost-only HTTP server that lives for the duration of the prompt.

The window posts the PIN back (or an empty PIN when it is closed unanswered), and
:func:`request_pin` returns it — a drop-in ``pin_provider`` for the facade::

    pw = ApplePasswords(pin_provider=request_pin)

The page is ``page.html`` next to this module; its look comes from a
stylesheet resolved in order: the ``css`` argument, a user override at
``~/.apwlib/pinwindow.css``, then the bundled ``default.css``.
"""

from __future__ import annotations

import ctypes
import http.server
import json
import secrets
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse

from apwlib.browsers import Browser, installed_browsers, resolve_browser
from apwlib.config import read_config
from apwlib.errors import NotPairedError
from apwlib.paths import BROWSER_PROFILE_DIR, PIN_STYLE_PATH
from apwlib.protocol import Status

_TIMEOUT = 120.0  # seconds a human gets to read the macOS dialog and type the PIN
_POLL = 0.2
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


class _PinServer(http.server.HTTPServer):
    """Localhost-only, single-use server: serves the page and style, receives one PIN."""

    def __init__(self, css: str | None = None) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.token = secrets.token_urlsafe(16)
        self.page = _page()
        self.css = _style(css)
        self.pin: str | None = None
        self.done = threading.Event()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/?token={self.token}"


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass  # keep stderr clean

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        server = cast(_PinServer, self.server)
        parsed = urlparse(self.path)
        if parsed.path == "/style.css":  # no secrets in styling; the token stays in the page URL
            self._respond(200, server.css.encode(), "text/css; charset=utf-8")
            return
        if parsed.path != "/" or parse_qs(parsed.query).get("token") != [server.token]:
            self.send_error(404)
            return
        self._respond(200, server.page.encode(), "text/html; charset=utf-8")

    def do_POST(self) -> None:
        server = cast(_PinServer, self.server)
        try:
            message = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except ValueError:
            message = {}
        if self.path != "/pin" or message.get("token") != server.token:
            self.send_error(404)
            return
        if not server.done.is_set():  # first answer wins (a close beacon may race a submit)
            server.pin = str(message.get("pin", ""))
            server.done.set()
        self._respond(200, b"{}", "application/json")


def _running_browser() -> Browser | None:
    """The installed browser the user is actually running, if any.

    Matches main browser processes only, ignoring our own managed instances (the
    daemon's headless browser and PIN windows), which run with profiles of ours.
    """
    try:
        processes = subprocess.run(
            ["ps", "-axo", "args"], capture_output=True, text=True, check=True
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return None

    def is_user_run(line: str, browser: Browser) -> bool:
        return (
            line.startswith(str(browser.binary))
            and str(BROWSER_PROFILE_DIR) not in line
            and _PROFILE_PREFIX not in line
        )

    return next(
        (b for b in installed_browsers() if any(is_user_run(line, b) for line in processes)),
        None,
    )


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


def _screen_size() -> tuple[int, int] | None:
    """Main-display size in points, straight from CoreGraphics.

    Plain display metrics need no TCC permission — unlike osascript, which raises
    an Automation consent prompt the first time.
    """
    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        cg.CGDisplayBounds.restype = _CGRect
        cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        bounds = cg.CGDisplayBounds(cg.CGMainDisplayID())
        return int(bounds.size.width), int(bounds.size.height)
    except OSError:
        return None


def _launch_window(binary: Path, url: str, profile: str) -> subprocess.Popen[bytes]:
    """Open ``url`` in a chromeless, dialog-sized app-mode window."""
    width, height = _WINDOW_SIZE
    args = [
        str(binary),
        f"--app={url}",
        f"--user-data-dir={profile}",
        # A throwaway profile invites first-run and promo infobars; keep the window clean.
        "--no-first-run",
        "--no-default-browser-check",
        "--test-type",  # suppresses the remaining infobars (promo/analytics banners)
        "--disable-sync",
        "--disable-default-apps",
        "--disable-component-update",
        "--disable-background-networking",
        "--disable-features=Translate",
        f"--window-size={width},{height}",
    ]
    if screen := _screen_size():
        x = max((screen[0] - width) // 2, 0)
        y = max((screen[1] - height) // 3, 0)  # a bit above center, like a system dialog
        args.append(f"--window-position={x},{y}")
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
    server = _PinServer(css)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix=_PROFILE_PREFIX) as profile:
            window = _launch_window(browser.binary, server.url, profile)
            try:
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if server.done.wait(_POLL):
                        if server.pin:
                            return server.pin
                        raise NotPairedError(Status.INVALID_SESSION, "pairing cancelled")
                    if window.poll() is not None:
                        raise NotPairedError(
                            Status.INVALID_SESSION, "PIN window closed before a code was entered"
                        )
                raise NotPairedError(Status.INVALID_SESSION, "timed out waiting for the PIN")
            finally:
                if window.poll() is None:
                    window.terminate()
                    try:
                        window.wait(5)
                    except subprocess.TimeoutExpired:
                        window.kill()
    finally:
        server.shutdown()
        server.server_close()
