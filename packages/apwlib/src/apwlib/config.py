"""Read/write ``~/.apwlib/config.json``."""

from __future__ import annotations

import json
from typing import Any

from apwlib.paths import CONFIG_PATH, ensure_data_dir


def read_config() -> dict[str, Any]:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_config(patch: dict[str, Any]) -> dict[str, Any]:
    ensure_data_dir()
    merged = {**read_config(), **patch}
    CONFIG_PATH.write_text(json.dumps(merged, indent=2))
    return merged
