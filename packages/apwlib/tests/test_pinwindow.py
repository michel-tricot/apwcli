"""Tests for the no-TTY PIN window (server + request_pin), without a real browser."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from apwlib import NotPairedError, pinwindow
from apwlib.browsers import Browser
from apwlib.pinwindow import _PinServer, request_pin


class _FakeWindow:
    """Stands in for the app-mode browser subprocess."""

    def __init__(self, exited: bool = False) -> None:
        self._returncode: int | None = 0 if exited else None
        self.terminated = False

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self) -> None:
        self.terminated = True
        self._returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        return 0


def _post_pin(url: str, pin: str, token: str | None = None) -> None:
    origin = url.split("/?", 1)[0]
    token = token if token is not None else parse_qs(urlparse(url).query)["token"][0]
    body = json.dumps({"token": token, "pin": pin}).encode()
    urllib.request.urlopen(urllib.request.Request(f"{origin}/pin", data=body), timeout=5)


@pytest.fixture
def fake_browser(monkeypatch: pytest.MonkeyPatch) -> Browser:
    browser = Browser(
        id="fake", name="Fake", binary=Path("/fake"), data_dir=Path("/fake"), brew_cask="fake"
    )
    monkeypatch.setattr(pinwindow, "_running_browser", lambda: None)
    monkeypatch.setattr(pinwindow, "resolve_browser", lambda _selected: browser)
    return browser


@pytest.fixture
def server() -> Iterator[_PinServer]:
    srv = _PinServer()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_serves_page_with_token(server: _PinServer) -> None:
    with urllib.request.urlopen(server.url, timeout=5) as resp:
        page = resp.read().decode()
    assert "Pair Apple Passwords" in page
    assert page.count("<input") == 6
    assert 'href="style.css"' in page


def test_serves_default_style(server: _PinServer) -> None:
    origin = server.url.split("/?", 1)[0]
    with urllib.request.urlopen(f"{origin}/style.css", timeout=5) as resp:
        css = resp.read().decode()
    assert ".boxes" in css  # the bundled default styles the code boxes


def test_serves_custom_style() -> None:
    srv = _PinServer(css="body { background: pink; }")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        origin = srv.url.split("/?", 1)[0]
        with urllib.request.urlopen(f"{origin}/style.css", timeout=5) as resp:
            assert resp.read().decode() == "body { background: pink; }"
    finally:
        srv.shutdown()
        srv.server_close()


def test_style_prefers_user_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    override = tmp_path / "pinwindow.css"
    override.write_text("main { color: red; }")
    monkeypatch.setattr(pinwindow, "PIN_STYLE_PATH", override)
    assert pinwindow._style(None) == "main { color: red; }"
    assert pinwindow._style("h1 {}") == "h1 {}"  # explicit css still wins


def test_rejects_bad_token(server: _PinServer) -> None:
    origin = server.url.split("/?", 1)[0]
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(f"{origin}/?token=wrong", timeout=5)


def test_rejects_bad_token_post(server: _PinServer) -> None:
    with pytest.raises(urllib.error.HTTPError):
        _post_pin(server.url, "123456", token="wrong")
    assert not server.done.is_set()


def test_receives_pin_once(server: _PinServer) -> None:
    _post_pin(server.url, "123456")
    assert server.done.is_set() and server.pin == "123456"
    _post_pin(server.url, "999999")  # a late close-beacon must not clobber the answer
    assert server.pin == "123456"


def test_request_pin_returns_submitted_pin(
    fake_browser: Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    def launch(binary: Path, url: str, profile: str) -> _FakeWindow:
        threading.Thread(target=_post_pin, args=(url, "123456"), daemon=True).start()
        return _FakeWindow()

    monkeypatch.setattr(pinwindow, "_launch_window", launch)
    assert request_pin(timeout=5) == "123456"


def test_request_pin_empty_pin_means_cancelled(
    fake_browser: Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    def launch(binary: Path, url: str, profile: str) -> _FakeWindow:
        threading.Thread(target=_post_pin, args=(url, ""), daemon=True).start()
        return _FakeWindow()

    monkeypatch.setattr(pinwindow, "_launch_window", launch)
    with pytest.raises(NotPairedError, match="cancelled"):
        request_pin(timeout=5)


def test_request_pin_window_closed(fake_browser: Browser, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pinwindow, "_launch_window", lambda b, u, p: _FakeWindow(exited=True))
    with pytest.raises(NotPairedError, match="closed"):
        request_pin(timeout=5)


def test_request_pin_times_out(fake_browser: Browser, monkeypatch: pytest.MonkeyPatch) -> None:
    window = _FakeWindow()
    monkeypatch.setattr(pinwindow, "_launch_window", lambda b, u, p: window)
    with pytest.raises(NotPairedError, match="timed out"):
        request_pin(timeout=0.5)
    assert window.terminated


def test_request_pin_without_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pinwindow, "_running_browser", lambda: None)
    monkeypatch.setattr(pinwindow, "resolve_browser", lambda _selected: None)
    with pytest.raises(NotPairedError, match="browser"):
        request_pin(timeout=1)


def _ps_result(lines: list[str]) -> object:
    class Result:
        stdout = "\n".join(lines)

    return Result()


def _browsers() -> list[Browser]:
    return [
        Browser(
            id=i,
            name=i.title(),
            binary=Path(f"/Applications/{i}"),
            data_dir=Path("/x"),
            brew_cask=i,
        )
        for i in ("brave", "chrome")
    ]


def test_running_browser_prefers_the_users_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pinwindow, "installed_browsers", _browsers)
    lines = [
        # The daemon's managed instance must not count as "the user's browser".
        "/Applications/brave --user-data-dir=" + str(pinwindow.BROWSER_PROFILE_DIR / "brave"),
        "/Applications/chrome",
    ]
    monkeypatch.setattr(pinwindow.subprocess, "run", lambda *a, **k: _ps_result(lines))
    browser = pinwindow._running_browser()
    assert browser is not None and browser.id == "chrome"


def test_running_browser_none_when_only_managed_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pinwindow, "installed_browsers", _browsers)
    lines = [
        "/Applications/brave --user-data-dir=" + str(pinwindow.BROWSER_PROFILE_DIR / "brave"),
        "/Applications/chrome --app=http://127.0.0.1:1/ --user-data-dir=/tmp/apwlib-pin-x",
    ]
    monkeypatch.setattr(pinwindow.subprocess, "run", lambda *a, **k: _ps_result(lines))
    assert pinwindow._running_browser() is None


@pytest.mark.skipif(sys.platform != "darwin", reason="CoreGraphics is macOS-only")
def test_screen_size_reports_the_display() -> None:
    size = pinwindow._screen_size()
    assert size is not None
    width, height = size
    assert width > 0 and height > 0


def test_screen_size_none_without_coregraphics(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_oserror(_path: str) -> None:
        raise OSError("no such library")

    monkeypatch.setattr(pinwindow.ctypes, "CDLL", raise_oserror)
    assert pinwindow._screen_size() is None
