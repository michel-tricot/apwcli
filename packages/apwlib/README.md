# apwlib

**Programmatic access to Apple Passwords (iCloud Keychain) on macOS** — the
Python library behind [`apwcli`](https://github.com/michel-tricot/apwcli).

```python
from apwlib import ApplePasswords

pw = ApplePasswords(pin_provider=lambda: input("PIN: "))
for entry in pw.get_password("github.com", "me@example.com"):
    print(entry.username, "->", entry.password)
```

Everything is managed for you: the first call auto-starts a background daemon
(a detached singleton that outlives your program) and, with a `pin_provider`,
pairs on demand by popping the macOS PIN dialog. Keep one `ApplePasswords`
instance around and call it whenever you need a credential.

## Install

```sh
pip install apwlib    # or: uv add apwlib
```

Requires macOS with a supported browser installed (Chrome, Brave, Edge, or
Chromium); the iCloud Passwords extension itself is downloaded automatically
from the Chrome Web Store.

## Usage

```python
from apwlib import ApplePasswords, ApwError, SessionError

pw = ApplePasswords(pin_provider=lambda: input("PIN: "))

# Accounts saved for a site. Matching is by registrable domain: a bare host,
# a full URL, or a subdomain all resolve to the same accounts.
for account in pw.get_login_names("github.com"):
    print(account.username, account.domain, account.title)

# Passwords — narrow with a username, or omit it for every match.
# An empty list means no match; reads don't raise for "not found".
for entry in pw.get_password("github.com", "me@example.com"):
    print(entry.username, "->", entry.password)

# Create or update a credential.
pw.save_account("example.com", "me@example.com", "s3cret-passw0rd")

# One-time codes: what's available, and the current code.
for code in pw.list_otp("github.com"):
    print(code.username, code.domain)
for code in pw.get_otp("github.com"):
    print(code.code)

# The paired session lives in the browser and can drop; catch SessionError
# to re-pair, or ApwError for anything protocol-level.
try:
    pw.get_login_names("github.com")
except SessionError:
    print("session dropped — pair again")
except ApwError as exc:
    print(f"request failed (status {int(exc.status)}): {exc}")
```

## Pairing

Pairing needs a 6-digit PIN that macOS displays, once per daemon lifetime.
A `pin_provider` callback handles it transparently; to drive it explicitly:

```python
from apwlib import ApplePasswords

pw = ApplePasswords()
pw.daemon.request_challenge()  # macOS shows a 6-digit PIN
pw.daemon.verify_challenge(input("PIN: "))
pw.daemon.wait_until_paired()
```

`pw.daemon` also exposes `start()`, `stop()`, and `status()`. A pairing cannot
outlive the daemon (the helper issues a fresh PIN per handshake by design), so
keeping the daemon alive is what keeps the PIN rare.

No terminal to prompt in? `apwlib.pinwindow.request_pin` is a ready-made
`pin_provider` that collects the PIN in a small on-screen window (six code
boxes, opened chromeless in an installed browser) — it's what `apwcli` uses
when stdin is not a TTY:

```python
from apwlib import ApplePasswords
from apwlib.pinwindow import request_pin

pw = ApplePasswords(pin_provider=request_pin)
```

The window is a plain HTML page with a bundled default stylesheet. Restyle it
by passing CSS text (`pin_provider=lambda: request_pin(css=...)`) or by
dropping a replacement at `~/.apwlib/pinwindow.css`.

## Data model

Reads return dataclasses (`PasswordEntry`, `OTPEntry`). Their shape, without a
daemon:

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

Every failure raises `ApwError` (or a subclass — `SessionError`,
`DaemonNotRunningError`, `NotPairedError`, `ServerError`) carrying a `Status`:

```python
from apwlib import SessionError, Status

try:
    raise SessionError(Status.INVALID_SESSION)
except SessionError as exc:
    print(int(exc.status))
    #> 9
```

See the [design notes](../../docs/design/apwlib.md) for how the library talks
to Apple Passwords and why a browser is involved.
