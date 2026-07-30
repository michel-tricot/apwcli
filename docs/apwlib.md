# apwlib

`apwlib` provides programmatic access to Apple Passwords (iCloud Keychain) on macOS. It
is the library behind the [`apwcli`](apwcli.md) command-line tool.

macOS only permits an approved browser to talk to the Apple Passwords helper, so `apwlib`
runs a small daemon that manages a headless browser and the official iCloud Passwords
extension; your Python code talks to that daemon over a local socket. See
[the design notes](design/apwlib.md) for why.

## Installation

```console
$ pip install apwlib
```

## Usage

The daemon is auto-managed: the first call spins it up as a detached, singleton process
that outlives your program and is reused afterwards. You only pair once with the macOS PIN
(via [apwcli](apwcli.md) `daemon pair`, or a `pin_provider` — see the [apwlib README](../packages/apwlib/README.md)):

```python
# needs a running daemon, so this block is not executed by the test suite
from apwlib import ApplePasswords

pw = ApplePasswords()  # auto-starts the daemon on first use
for entry in pw.get_login_names("https://github.com"):
    print(entry.username, entry.domain)
```

### Entries are typed

Results are dataclasses. `PasswordEntry.from_raw` shows the shape without needing a daemon:

```python
from apwlib import PasswordEntry

entry = PasswordEntry.from_raw(
    {"USR": "me@example.com", "PWD": "hunter2", "sites": ["https://github.com"]}
)
print(entry.username, entry.domain, entry.password)
#> me@example.com https://github.com hunter2
```

A password the vault withholds (`"Not Included"`) becomes `None`:

```python
from apwlib import PasswordEntry

entry = PasswordEntry.from_raw({"USR": "a", "PWD": "Not Included", "sites": ["x"]})
print(entry.password)
#> None
```

### Errors

Every failure raises an `ApwError` (or a subclass) carrying a `Status`:

```python
from apwlib import SessionError, Status

try:
    raise SessionError(Status.INVALID_SESSION)
except SessionError as exc:
    print(int(exc.status))
    #> 9
```

Python code blocks in this file are executed and lint-checked on every test run.
