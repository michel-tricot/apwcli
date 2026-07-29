"""Greeting utilities."""


def greet(name: str) -> str:
    """Return a greeting for ``name``.

    Raises ValueError if ``name`` is empty or whitespace.
    """
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("name must not be empty")
    return f"Hello, {cleaned}!"
