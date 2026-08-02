"""Daemon server internals that don't need a real browser."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest
from apwlib.browsers import BrowserInfo
from apwlib.daemon import server
from apwlib.protocol import Status


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

    async def pair_challenge(self) -> dict:
        return {"ready": True}

    async def pair_verify(self, pin: str) -> dict:
        return {"paired": pin == "123456"}


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

    def __init__(self, *, ready: bool, channel: object | None = None) -> None:
        self._ready = ready
        self._channel = channel

    def extension_ready(self, extension_id: str) -> bool:
        return self._ready

    def extension(self, extension_id: str) -> object:
        if self._channel is None:
            raise LookupError(extension_id)
        return self._channel


class _PairingChannel:
    """Scripts a pairing worker: ``request`` acks, ``status`` walks through ``states``."""

    def __init__(self, states: list[dict]) -> None:
        self._states = list(states)
        self.calls: list[tuple[str, dict | None]] = []

    async def call(self, command: str, params: dict | None = None, *, timeout: float = 30.0) -> Any:  # noqa: ASYNC109 - mirrors chauffeur's ExtensionChannel.call
        self.calls.append((command, params))
        if command == "request":
            return {"status": 0}
        return self._states.pop(0) if len(self._states) > 1 else self._states[0]


def _pairing_bridge(states: list[dict]) -> tuple[server.ExtensionBridge, _PairingChannel]:
    channel = _PairingChannel(states)
    return server.ExtensionBridge(cast(Any, _FakeManagedBrowser(ready=True, channel=channel)), "abc"), channel


@pytest.mark.anyio
async def test_request_returns_no_bridge_when_worker_absent() -> None:
    bridge = server.ExtensionBridge(cast(Any, _FakeManagedBrowser(ready=False)), "abc")
    resp = await bridge.request({"cmd": 4, "qid": "q", "body": {}})
    assert resp["error"] == server.WIRE_NO_BRIDGE


@pytest.mark.anyio
async def test_request_forwards_to_worker_channel() -> None:
    channel = _FakeChannel(result={"data": {"STATUS": 0}})
    bridge = server.ExtensionBridge(cast(Any, _FakeManagedBrowser(ready=True, channel=channel)), "abc")

    resp = await bridge.request({"cmd": 4, "qid": "q", "body": {}})

    assert resp == {"data": {"STATUS": 0}}
    assert channel.calls == [("request", {"cmd": 4, "qid": "q", "body": {}})]


@pytest.mark.anyio
async def test_pairing_pulls_live_state_from_worker() -> None:
    channel = _FakeChannel(result={"paired": True, "state": "SessionKeySet"})
    bridge = server.ExtensionBridge(cast(Any, _FakeManagedBrowser(ready=True, channel=channel)), "abc")

    assert await bridge.pairing() == {"paired": True, "state": "SessionKeySet"}
    assert channel.calls == [("status", None)]  # pulled, not cached


@pytest.mark.anyio
async def test_pairing_unpaired_while_worker_boots() -> None:
    bridge = server.ExtensionBridge(cast(Any, _FakeManagedBrowser(ready=False)), "abc")
    assert await bridge.pairing() == {"paired": False, "state": None}


@pytest.mark.anyio
async def test_pairing_tolerates_bridge_handlers_not_yet_registered() -> None:
    # The channel installs (ready=True) a beat before the appended bridge registers its
    # handlers; a status poll in that window raises JSError and must read as unpaired,
    # not tear down the client connection reply-less.
    from chauffeur import JSError

    channel = _FakeChannel(error=JSError("no JS handler for command: status"))
    bridge = server.ExtensionBridge(cast(Any, _FakeManagedBrowser(ready=True, channel=channel)), "abc")
    assert await bridge.pairing() == {"paired": False, "state": None}


@pytest.mark.anyio
async def test_request_answers_when_bridge_handlers_not_yet_registered() -> None:
    from chauffeur import JSError

    channel = _FakeChannel(error=JSError("no JS handler for command: request"))
    bridge = server.ExtensionBridge(cast(Any, _FakeManagedBrowser(ready=True, channel=channel)), "abc")

    resp = await bridge.request({"cmd": 4, "qid": "q", "body": {}})

    assert resp["status"] == int(Status.INVALID_SESSION)
    assert "no JS handler" in resp["error"]


@pytest.mark.anyio
async def test_pair_challenge_waits_until_ready_for_the_pin() -> None:
    # Submitting the PIN before the challenge reaches MSG1Set wedges the handshake, so
    # pair_challenge must not reply until the worker's state settles there.
    bridge, channel = _pairing_bridge(
        [
            {"paired": False, "state": "NotInSession"},
            {"paired": False, "state": "ChallengeSent"},
            {"paired": False, "state": "MSG1Set"},
        ]
    )
    assert await bridge.pair_challenge() == {"ready": True}
    assert channel.calls[0] == ("request", {"cmd": 2})
    assert [c for c in channel.calls if c[0] == "status"] == [("status", None)] * 3


@pytest.mark.anyio
async def test_pair_challenge_timeout_is_not_fatal() -> None:
    # A divergent state machine must not hang pairing here: on timeout the reply is
    # ready=False and the caller proceeds to the PIN anyway.
    bridge, _channel = _pairing_bridge([{"paired": False, "state": "ChallengeSent"}])
    assert await bridge.pair_challenge(timeout=0.05) == {"ready": False}


@pytest.mark.anyio
async def test_pair_verify_reports_paired() -> None:
    bridge, channel = _pairing_bridge(
        [
            {"paired": False, "state": "MSG1Set"},
            {"paired": True, "state": "SessionKeySet"},
        ]
    )
    assert await bridge.pair_verify("123456") == {"paired": True}
    assert channel.calls[0] == ("request", {"cmd": 2, "pin": "123456"})


@pytest.mark.anyio
async def test_pair_verify_fails_fast_on_collapsed_handshake() -> None:
    # A wrong PIN collapses MSG1Set -> NotInSession, often before the first poll. Since
    # verify runs with a handshake in flight, NotInSession can only mean rejection —
    # report it on the first read, not after the full timeout.
    bridge, channel = _pairing_bridge([{"paired": False, "state": "NotInSession"}])
    assert await bridge.pair_verify("000000") == {"paired": False}
    assert [c for c in channel.calls if c[0] == "status"] == [("status", None)]


@pytest.mark.anyio
async def test_pair_ops_forward_bridge_errors() -> None:
    # No worker attached: the pairing ops must forward the bridge error (so the client
    # raises it) rather than dress it up as ready/rejected.
    bridge = server.ExtensionBridge(cast(Any, _FakeManagedBrowser(ready=False)), "abc")
    assert (await bridge.pair_challenge())["error"] == server.WIRE_NO_BRIDGE
    assert (await bridge.pair_verify("123456"))["error"] == server.WIRE_NO_BRIDGE


_BROWSER = BrowserInfo(id="brave", name="Brave", binary=Path("/x"))


@pytest.mark.anyio
async def test_pair_ops_are_routed() -> None:
    for line, expected in [
        (b'{"op": "pair_challenge"}\n', {"ready": True}),
        (b'{"op": "pair_verify", "pin": "123456"}\n', {"paired": True}),
        (b'{"op": "pair_verify", "pin": "000000"}\n', {"paired": False}),
    ]:
        writer = _FakeWriter()
        await server._handle_client(
            cast(Any, _FakeReader(line)),
            cast(Any, writer),
            cast(Any, _FakeSession()),
            asyncio.Event(),
            _BROWSER,
            1,
        )
        assert json.loads(writer.buf.decode()) == expected


@pytest.mark.anyio
async def test_status_reports_browser_and_pid() -> None:
    reader = _FakeReader(b'{"op": "status"}\n')
    writer = _FakeWriter()

    await server._handle_client(
        cast(Any, reader),
        cast(Any, writer),
        cast(Any, _FakeSession()),
        asyncio.Event(),
        _BROWSER,
        3131,
    )

    resp = json.loads(writer.buf.decode())
    assert resp["running"] is True
    assert resp["bridge"] is True and resp["paired"] is False
    assert resp["browser"] == "Brave" and resp["browser_pid"] == 3131
    assert resp["pairing_state"] == "MSG1Set"


@pytest.mark.anyio
async def test_stop_op_sets_the_stop_event() -> None:
    writer = _FakeWriter()
    stop = asyncio.Event()

    await server._handle_client(
        cast(Any, _FakeReader(b'{"op": "stop"}\n')),
        cast(Any, writer),
        cast(Any, _FakeSession()),
        stop,
        _BROWSER,
        1,
    )

    assert stop.is_set()
    assert json.loads(writer.buf.decode()) == {"stopping": True}


@pytest.mark.anyio
async def test_malformed_request_gets_an_error_reply() -> None:
    # Bad JSON must be answered, not dropped: hanging up surfaces on the client as
    # a decode error instead of an ApwError.
    writer = _FakeWriter()

    await server._handle_client(
        cast(Any, _FakeReader(b"not json\n")),
        cast(Any, writer),
        cast(Any, _FakeSession()),
        asyncio.Event(),
        _BROWSER,
        1,
    )

    resp = json.loads(writer.buf.decode())
    assert resp == {"status": int(Status.INVALID_PARAM), "error": "malformed request"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
