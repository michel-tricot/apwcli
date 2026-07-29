# apwcli

`apwcli` is the command-line interface for [apwlib](apwlib.md).

## Installation

```console
$ pip install apwcli
```

## Usage

Greet someone:

```console
$ apwcli greet world
Hello, world!
```

An empty name is rejected with exit code 1:

```console
$ apwcli greet "   "
error: name must not be empty
```

Show the version:

```console
$ apwcli --version
apwcli 0.1.0
```

## Programmatic entry point

The CLI can also be invoked from Python, which is how it is tested:

```python
from apwcli.cli import main

exit_code = main(["greet", "world"])
#> Hello, world!
assert exit_code == 0
```

Python code blocks in this file are executed and lint-checked on every test run
(see `tests/test_docs.py`), so the examples above are guaranteed to work.
