"""Daemon server internals that don't need a real browser."""

from __future__ import annotations

import asyncio

import pytest
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


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
