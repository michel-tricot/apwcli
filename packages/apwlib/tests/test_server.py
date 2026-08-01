"""Daemon server internals that don't need a real browser."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest
from apwlib.browsers import Browser
from apwlib.daemon import server


class _FakeChild:
    """A browser child whose wait() resolves when we say it exited."""

    def __init__(self) -> None:
        self._exited = asyncio.Event()

    def exit(self) -> None:
        self._exited.set()

    async def wait(self) -> int:
        await self._exited.wait()
        return 0


@pytest.mark.anyio
async def test_watch_child_triggers_stop_on_browser_exit() -> None:
    child = _FakeChild()
    stop: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    watcher = asyncio.create_task(server._watch_child(child, stop))

    assert not stop.done()
    child.exit()
    await asyncio.wait_for(stop, timeout=1)
    assert stop.done()
    await watcher


@pytest.mark.anyio
async def test_watch_child_noop_if_stop_already_set() -> None:
    child = _FakeChild()
    stop: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    stop.set_result(None)  # daemon already shutting down for another reason
    child.exit()
    await server._watch_child(child, stop)  # must not raise (no double set_result)


class _FakeReader:
    def __init__(self, line: bytes) -> None:
        self._line = line

    async def readline(self) -> bytes:
        return self._line


class _FakeWriter:
    def __init__(self) -> None:
        self.buf = b""

    def write(self, data: bytes) -> None:
        self.buf += data

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


class _FakeSession:
    ready = True
    paired = False
    pairing_state = "MSG1Set"


@pytest.mark.anyio
async def test_status_reports_browser_and_pid() -> None:
    reader = _FakeReader(b'{"op": "status"}\n')
    writer = _FakeWriter()
    browser = Browser(
        id="brave", name="Brave", binary=Path("/x"), data_dir=Path("/x"), brew_cask="brave-browser"
    )
    child = type("_Child", (), {"pid": 3131})()
    stop: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    await server._handle_client(
        cast(Any, reader),
        cast(Any, writer),
        cast(Any, _FakeSession()),
        stop,
        browser,
        cast(Any, child),
    )

    resp = json.loads(writer.buf.decode())
    assert resp["running"] is True
    assert resp["bridge"] is True and resp["paired"] is False
    assert resp["browser"] == "Brave" and resp["browser_pid"] == 3131
    assert resp["pairing_state"] == "MSG1Set"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
