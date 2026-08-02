"""Tests for the no-TTY PIN window (request_pin over a faked chauffeur window)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from apwlib import NotPairedError, pinwindow
from apwlib.browsers import Browser
from apwlib.pinwindow import request_pin
from chauffeur.launch import LaunchError


class _FakeWindow:
    """Stands in for chauffeur's SyncBrowser: records the spec, scripts serve()."""

    def __init__(self, spec) -> None:
        self.spec = spec
        self.handlers: dict[str, Callable[[dict], object]] = {}
        self.closed = False

    def command(self, name: str | None = None, *, strict: bool = False):
        def register(fn):
            self.handlers[name or fn.__name__] = fn
            return fn

        return register

    def _answer(self, pin: str) -> None:
        self.handlers["pin"]({"pin": pin})

    def serve(self, *, until: threading.Event | None = None) -> None:
        raise NotImplementedError  # overridden per test

    def __enter__(self) -> _FakeWindow:
        return self

    def __exit__(self, *exc: object) -> None:
        self.closed = True


def _install(monkeypatch: pytest.MonkeyPatch, fake_cls: type[_FakeWindow]) -> list[_FakeWindow]:
    created: list[_FakeWindow] = []

    def factory(spec) -> _FakeWindow:
        window = fake_cls(spec)
        created.append(window)
        return window

    monkeypatch.setattr(pinwindow, "SyncBrowser", factory)
    return created


@pytest.fixture
def fake_browser(monkeypatch: pytest.MonkeyPatch) -> Browser:
    browser = Browser(id="fake", name="Fake", binary=Path("/fake"), brew_cask="fake")
    monkeypatch.setattr(pinwindow, "_running_browser", lambda: None)
    monkeypatch.setattr(pinwindow, "resolve_browser", lambda _selected: browser)
    return browser


def test_request_pin_returns_submitted_pin(
    fake_browser: Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Submits(_FakeWindow):
        def serve(self, *, until: threading.Event | None = None) -> None:
            self._answer("123456")
            assert until is not None and until.wait(5)

    created = _install(monkeypatch, Submits)
    assert request_pin(timeout=5) == "123456"

    window = created[0]
    assert window.closed
    # The window is a chromeless app page served from the scratch dir, sized like a dialog.
    assert window.spec.browser == fake_browser.binary
    assert window.spec.headless is False
    assert window.spec.url.name == "page.html"
    assert window.spec.url.parent.name.startswith("apwlib-pin-")
    assert window.spec.app is True
    assert window.spec.window.size == pinwindow._WINDOW_SIZE
    assert window.spec.window.position == "top"  # chauffeur pins it to the top of the screen


def test_request_pin_first_answer_wins(
    fake_browser: Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    class SubmitThenCloseBeacon(_FakeWindow):
        def serve(self, *, until: threading.Event | None = None) -> None:
            self._answer("123456")
            self._answer("")  # the pagehide close beacon racing the submit must not win
            assert until is not None and until.wait(5)

    _install(monkeypatch, SubmitThenCloseBeacon)
    assert request_pin(timeout=5) == "123456"


def test_request_pin_empty_pin_means_cancelled(
    fake_browser: Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Cancels(_FakeWindow):
        def serve(self, *, until: threading.Event | None = None) -> None:
            self._answer("")  # the page's close beacon posts an empty PIN
            assert until is not None and until.wait(5)

    _install(monkeypatch, Cancels)
    with pytest.raises(NotPairedError, match="cancelled"):
        request_pin(timeout=5)


def test_request_pin_window_closed(fake_browser: Browser, monkeypatch: pytest.MonkeyPatch) -> None:
    class ClosesUnanswered(_FakeWindow):
        def serve(self, *, until: threading.Event | None = None) -> None:
            # The user closed the window: serve() returns on its own. Mimic chauffeur's
            # real contract, which sets `until` on the way out regardless of the cause.
            if until is not None:
                until.set()

    _install(monkeypatch, ClosesUnanswered)
    with pytest.raises(NotPairedError, match="closed"):
        request_pin(timeout=5)


def test_request_pin_times_out(fake_browser: Browser, monkeypatch: pytest.MonkeyPatch) -> None:
    class NeverAnswers(_FakeWindow):
        def serve(self, *, until: threading.Event | None = None) -> None:
            assert until is not None and until.wait(5)  # released by the timeout timer

    created = _install(monkeypatch, NeverAnswers)
    with pytest.raises(NotPairedError, match="timed out"):
        request_pin(timeout=0.2)
    assert created[0].closed


def test_request_pin_launch_failure(fake_browser: Browser, monkeypatch: pytest.MonkeyPatch) -> None:
    class FailsToOpen(_FakeWindow):
        def __enter__(self) -> _FakeWindow:
            raise LaunchError("no DevTools")

    _install(monkeypatch, FailsToOpen)
    with pytest.raises(NotPairedError, match="failed to open"):
        request_pin(timeout=1)


def test_request_pin_without_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pinwindow, "_running_browser", lambda: None)
    monkeypatch.setattr(pinwindow, "resolve_browser", lambda _selected: None)
    with pytest.raises(NotPairedError, match="browser"):
        request_pin(timeout=1)


def test_page_posts_pin_over_chauffeur_channel() -> None:
    page = pinwindow._page()
    assert page.count("<input") == 6
    assert 'href="style.css"' in page  # served as a file:// sibling of the page
    assert 'py_chauffeur.notify("pin"' in page


def test_style_prefers_user_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    override = tmp_path / "pinwindow.css"
    override.write_text("main { color: red; }")
    monkeypatch.setattr(pinwindow, "PIN_STYLE_PATH", override)
    assert pinwindow._style(None) == "main { color: red; }"
    assert pinwindow._style("h1 {}") == "h1 {}"  # explicit css still wins


def test_style_defaults_to_bundled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pinwindow, "PIN_STYLE_PATH", tmp_path / "absent.css")
    assert ".boxes" in pinwindow._style(None)  # the bundled default styles the code boxes


def _ps_result(lines: list[str]) -> object:
    class Result:
        stdout = "\n".join(lines)

    return Result()


def _browsers() -> list[Browser]:
    return [
        Browser(id=i, name=i.title(), binary=Path(f"/Applications/{i}"), brew_cask=i)
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
        (
            "/Applications/chrome --app=file:///tmp/apwlib-pin-x/page.html "
            "--user-data-dir=/tmp/apwlib-pin-x/profile"
        ),
    ]
    monkeypatch.setattr(pinwindow.subprocess, "run", lambda *a, **k: _ps_result(lines))
    assert pinwindow._running_browser() is None
