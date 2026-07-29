# apwlib

`apwlib` is the core library behind `apwcli`. It is published as its own package
and can be used directly.

## Installation

```console
$ pip install apwlib
```

## Usage

Greet someone:

```python
from apwlib import greet

print(greet("world"))
#> Hello, world!
```

Leading and trailing whitespace in the name is stripped:

```python
from apwlib import greet

assert greet("  world  ") == "Hello, world!"
```

An empty name raises `ValueError`:

```python
from apwlib import greet

try:
    greet("   ")
except ValueError as exc:
    print(exc)
    #> name must not be empty
```

Python code blocks in this file are executed and lint-checked on every test run
(see `tests/test_docs.py`), so the examples above are guaranteed to work.
