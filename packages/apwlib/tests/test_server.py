"""Daemon server internals that don't need a real browser."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest
from apwlib.browsers import Browser
from apwlib.daemon import server


class _FakeManaged:
    """A chauffeur browser whose serve() returns when we say it exited."""

    def __init__(self) -> None:
        self._exited = asyncio.Event()

    def exit(self) -> None:
        self._exited.set()

    async def serve(self) -> None:
        await self._exited.wait()


@pytest.mark.anyio
async def test_watch_browser_triggers_stop_on_browser_exit() -> None:
    managed = _FakeManaged()
    stop: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    watcher = asyncio.create_task(server._watch_browser(cast(Any, managed), stop))

    assert not stop.done()
    managed.exit()
    await asyncio.wait_for(stop, timeout=1)
    assert stop.done()
    await watcher


@pytest.mark.anyio
async def test_watch_browser_noop_if_stop_already_set() -> None:
    managed = _FakeManaged()
    stop: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    stop.set_result(None)  # daemon already shutting down for another reason
    managed.exit()
    await server._watch_browser(cast(Any, managed), stop)  # must not raise (no double set)


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

    async def pairing(self) -> dict:
        return {"paired": False, "state": "MSG1Set"}


class _FakeChannel:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls: list[tuple[str, dict | None]] = []

    async def call(self, command: str, params: dict | None = None, *, timeout: float = 30.0) -> Any:  # noqa: ASYNC109 - mirrors chauffeur's ExtensionChannel.call
        self.calls.append((command, params))
        if self._error is not None:
            raise self._error
        return self._result


class _FakeManagedBrowser:
    """Stands in for a chauffeur Browser's extension worker-channel surface."""

    def __init__(
        self, *, ready: bool, channel: _FakeChannel | None = None, lookup_error: bool = False
    ) -> None:
        self._ready = ready
        self._channel = channel
        self._lookup_error = lookup_error

    def extension_ready(self, extension_id: str) -> bool:
        return self._ready

    def extension(self, extension_id: str) -> _FakeChannel:
        if self._lookup_error or self._channel is None:
            raise LookupError(extension_id)
        return self._channel


@pytest.mark.anyio
async def test_request_returns_no_bridge_when_worker_absent() -> None:
    bridge = server.ExtensionBridge(cast(Any, _FakeManagedBrowser(ready=False)))
    bridge.extension_id = "abc"
    resp = await bridge.request({"cmd": 4, "qid": "q", "body": {}})
    assert resp["error"] == server.WIRE_NO_BRIDGE


@pytest.mark.anyio
async def test_request_forwards_to_worker_channel() -> None:
    channel = _FakeChannel(result={"data": {"STATUS": 0}})
    managed = _FakeManagedBrowser(ready=True, channel=channel)
    bridge = server.ExtensionBridge(cast(Any, managed))
    bridge.extension_id = "abc"

    resp = await bridge.request({"cmd": 4, "qid": "q", "body": {}})

    assert resp == {"data": {"STATUS": 0}}
    assert channel.calls == [("request", {"cmd": 4, "qid": "q", "body": {}})]


@pytest.mark.anyio
async def test_request_maps_evicted_worker_to_no_bridge() -> None:
    managed = _FakeManagedBrowser(ready=True, lookup_error=True)
    bridge = server.ExtensionBridge(cast(Any, managed))
    bridge.extension_id = "abc"
    resp = await bridge.request({"cmd": 4, "qid": "q", "body": {}})
    assert resp["error"] == server.WIRE_NO_BRIDGE


@pytest.mark.anyio
async def test_request_maps_call_failure_to_server_error() -> None:
    channel = _FakeChannel(error=RuntimeError("worker died"))
    managed = _FakeManagedBrowser(ready=True, channel=channel)
    bridge = server.ExtensionBridge(cast(Any, managed))
    bridge.extension_id = "abc"
    resp = await bridge.request({"cmd": 4, "qid": "q", "body": {}})
    assert resp["status"] == server.Status.SERVER_ERROR
    assert "worker died" in resp["error"]


@pytest.mark.anyio
async def test_pairing_pulls_live_state_from_worker() -> None:
    channel = _FakeChannel(result={"paired": True, "state": "SessionKeySet"})
    bridge = server.ExtensionBridge(cast(Any, _FakeManagedBrowser(ready=True, channel=channel)))
    bridge.extension_id = "abc"

    assert await bridge.pairing() == {"paired": True, "state": "SessionKeySet"}
    assert channel.calls == [("status", None)]  # pulled, not cached


@pytest.mark.anyio
async def test_pairing_unpaired_when_worker_absent() -> None:
    bridge = server.ExtensionBridge(cast(Any, _FakeManagedBrowser(ready=False)))
    bridge.extension_id = "abc"
    assert await bridge.pairing() == {"paired": False, "state": None}


@pytest.mark.anyio
async def test_pairing_unpaired_on_call_failure() -> None:
    channel = _FakeChannel(error=RuntimeError("worker died"))
    bridge = server.ExtensionBridge(cast(Any, _FakeManagedBrowser(ready=True, channel=channel)))
    bridge.extension_id = "abc"
    assert await bridge.pairing() == {"paired": False, "state": None}


@pytest.mark.anyio
async def test_status_reports_browser_and_pid() -> None:
    reader = _FakeReader(b'{"op": "status"}\n')
    writer = _FakeWriter()
    browser = Browser(id="brave", name="Brave", binary=Path("/x"), brew_cask="brave-browser")
    stop: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    await server._handle_client(
        cast(Any, reader),
        cast(Any, writer),
        cast(Any, _FakeSession()),
        stop,
        browser,
        3131,
    )

    resp = json.loads(writer.buf.decode())
    assert resp["running"] is True
    assert resp["bridge"] is True and resp["paired"] is False
    assert resp["browser"] == "Brave" and resp["browser_pid"] == 3131
    assert resp["pairing_state"] == "MSG1Set"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
