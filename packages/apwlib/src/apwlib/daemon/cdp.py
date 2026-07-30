"""Minimal Chrome DevTools Protocol client: load an unpacked extension."""

from __future__ import annotations

import asyncio
import json
import urllib.request

import websockets


async def _debugger_url(port: int, attempts: int = 60, delay: float = 0.25) -> str:
    endpoint = f"http://127.0.0.1:{port}/json/version"
    for _ in range(attempts):
        try:
            raw = await asyncio.to_thread(
                lambda: urllib.request.urlopen(endpoint, timeout=1).read()
            )
            data = json.loads(raw)
            if url := data.get("webSocketDebuggerUrl"):
                return url
        except (OSError, ValueError):
            pass
        await asyncio.sleep(delay)
    raise RuntimeError("Browser DevTools endpoint did not start")


async def load_unpacked_extension(devtools_port: int, extension_path: str) -> None:
    """Load an unpacked extension via ``Extensions.loadUnpacked`` over CDP."""
    url = await _debugger_url(devtools_port)
    async with websockets.connect(url, max_size=None) as socket:
        await socket.send(
            json.dumps(
                {"id": 1, "method": "Extensions.loadUnpacked", "params": {"path": extension_path}}
            )
        )
        async with asyncio.timeout(15):
            while True:
                message = json.loads(await socket.recv())
                if message.get("id") == 1:
                    if error := message.get("error"):
                        raise RuntimeError(
                            f"Extensions.loadUnpacked failed: {error.get('message')}"
                        )
                    return
