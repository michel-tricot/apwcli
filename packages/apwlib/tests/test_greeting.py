import pytest
from apwlib import greet


def test_greet() -> None:
    assert greet("world") == "Hello, world!"


def test_greet_strips_whitespace() -> None:
    assert greet("  world  ") == "Hello, world!"


def test_greet_empty_name_raises() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        greet("   ")
