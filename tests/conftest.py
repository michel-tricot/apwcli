"""Shared fixtures for the CLI tests."""

from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def _assume_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Present as macOS so CliRunner reaches command logic.

    The CLI gates on macOS once, at startup (the root callback), and CliRunner exercises
    that gate — so on a non-mac CI runner every command would otherwise exit "requires
    macOS" before its logic runs. Tests that specifically want non-mac re-patch this.
    """
    monkeypatch.setattr(sys, "platform", "darwin")
