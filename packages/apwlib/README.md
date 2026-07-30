# apwlib

Programmatic access to Apple Passwords (iCloud Keychain) on macOS — the library behind
the [`apwcli`](https://github.com/micheltricot/apwcli) command-line tool.

macOS only lets an approved browser reach the Apple Passwords helper, so `apwlib` runs a
small daemon that manages a headless browser and the official iCloud Passwords extension.
Your code talks to that daemon over a local socket via the `ApplePasswords` facade. See
the [design notes](../../docs/design/apwlib.md) for why.

The daemon is managed for you: the first call auto-starts it as a detached, singleton
process that outlives your program and is reused by later calls. You don't run it by hand.

## Installation

```console
$ pip install apwlib
```

Requires macOS with the iCloud Passwords extension installed in a supported browser
(Chrome, Brave, Edge, or Chromium).

## Pairing (once)

Auto-start brings the daemon up on first use; pairing needs the macOS PIN once per
session. The easiest way is to pass a `pin_provider` — then any call pairs on demand (pops
the dialog, asks for the code) and proceeds:

```python
# needs a running daemon, so this block is not executed
from apwlib import ApplePasswords

pw = ApplePasswords(pin_provider=lambda: input("PIN: "))
print(pw.get_login_names("github.com"))  # pairs automatically the first time
```

Or drive it explicitly via `pw.daemon` (which also backs `daemon start`/`stop`/`status`):

```python
# needs a running daemon, so this block is not executed
from apwlib import ApplePasswords

pw = ApplePasswords()
pw.daemon.request_challenge()  # macOS shows a 6-digit PIN
pw.daemon.verify_challenge(input("PIN: "))
pw.daemon.wait_until_paired()
```

## Full example

The first call auto-starts the managed daemon; later calls reuse it. Each method opens a
short-lived connection, so you can keep one `ApplePasswords` instance around and call it
whenever you need a credential.

```python
# needs a running daemon, so this block is not executed
from apwlib import ApplePasswords, ApwError, SessionError

pw = ApplePasswords(pin_provider=lambda: input("PIN: "))  # auto-starts and auto-pairs

# List the accounts saved for a site. Matching is by registrable domain, so a bare
# host, a full URL, or a subdomain all resolve to the same accounts.
for account in pw.get_login_names("github.com"):
    print(account.username, account.domain, account.title)

# Fetch the password for one account (narrow with a username, or omit it for every
# match). An empty list means no match — reads don't raise for "not found".
for entry in pw.get_password("github.com", "me@example.com"):
    print(entry.username, "->", entry.password)

# Create or update a credential.
pw.save_account("example.com", "me@example.com", "s3cret-passw0rd")

# One-time codes: list what's available, or fetch the current code.
for code in pw.list_otp("github.com"):
    print(code.username, code.domain)
for code in pw.get_otp("github.com"):
    print(code.code)

# The session lives in the browser and can drop (e.g. the extension is evicted);
# catch SessionError to re-pair, or ApwError for anything protocol-level.
try:
    pw.get_login_names("github.com")
except SessionError:
    print("session dropped — pair again")
except ApwError as exc:
    print(f"request failed (status {int(exc.status)}): {exc}")
```

## Data model

Reads return dataclasses. You can see their shape without a daemon via `from_raw`:

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

## Errors

Every failure raises an `ApwError` (or a subclass — `SessionError`, `DaemonNotRunningError`,
`NotPairedError`, `ServerError`) carrying a `Status`:

```python
from apwlib import SessionError, Status

try:
    raise SessionError(Status.INVALID_SESSION)
except SessionError as exc:
    print(int(exc.status))
    #> 9
```

See the [documentation](../../docs/apwlib.md) and the [design notes](../../docs/design/apwlib.md).
