<div align="center">

# 🔑 `apwlib`

**Apple Passwords (iCloud Keychain) as a typed Python API.**
The library behind [`apwcli`](https://github.com/michel-tricot/apwcli).

[![CI](https://github.com/michel-tricot/apwcli/actions/workflows/ci.yml/badge.svg)](https://github.com/michel-tricot/apwcli/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](../../LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](#)

[**Website**](https://michel-tricot.github.io/apwcli/) ·
[API reference](https://michel-tricot.github.io/apwcli/reference/) ·
[Examples](../../examples) ·
[How it works](../../docs/design/apwlib.md)

</div>

---

Apple brokers keychain access through a helper that only runs inside an
approved browser — there is no public API. `apwlib` runs that plumbing for
you: a background daemon hosts the real iCloud Passwords extension in a
headless browser, pairs with the macOS PIN once, and your code gets a small,
typed facade.

- **Typed facade** — `get_password`, `save_password`, `get_otp`, `list_otp`
  returning dataclasses, keyed by site URL
- **Zero babysitting** — the daemon auto-starts as a detached singleton and is
  reused across programs and runs
- **Transparent pairing** — pass a `pin_provider` and an unpaired call pairs
  itself; `apwlib.pinwindow` collects the PIN on screen when there's no terminal
- **Nothing leaves your Mac** — Apple's own extension does the crypto (SRP
  pairing, AES-GCM per command); apwlib is local transport around it
- **Small public surface** — the package root plus `apwlib.pinwindow` and
  `apwlib.diagnostics`; everything else is private and underscore-named

## Install

```sh
uv add apwlib    # or: pip install apwlib
```

Requires macOS with a supported browser installed (Chrome, Brave, Edge, or
Chromium); the iCloud Passwords extension itself is downloaded automatically
from the Chrome Web Store.

## Quickstart

```python
from apwlib import ApplePasswords

pw = ApplePasswords(pin_provider=lambda: input("PIN: "))

for entry in pw.get_password("github.com"):
    print(entry.username)  # entry.password holds the real value
```

The first call starts the daemon and, if the session isn't paired yet, macOS
shows a 6-digit PIN and your `pin_provider` supplies it. Keep one
`ApplePasswords` instance around and call it whenever you need a credential.

## Usage

```python
from apwlib import ApplePasswords, ApwError, SessionError

pw = ApplePasswords(pin_provider=lambda: input("PIN: "))

# Entries for a site. Matching is by registrable domain: a bare host, a full
# URL, or a subdomain all resolve to the same entries. Narrow with a username,
# or omit it for every match. An empty list means no match; reads don't raise
# for "not found".
for entry in pw.get_password("github.com", "me@example.com"):
    login(entry.username, entry.password)

# Create or update a credential.
pw.save_password("example.com", "me@example.com", "s3cret-passw0rd")

# One-time codes: what's available, and the current code.
for code in pw.list_otp("github.com"):
    print(code.username, code.domain)
for code in pw.get_otp("github.com"):
    print(code.code)

# The paired session lives in the browser and can drop; catch SessionError
# to re-pair, or ApwError for anything protocol-level.
try:
    pw.get_password("github.com")
except SessionError:
    print("session dropped — pair again")
except ApwError as exc:
    print(f"request failed (status {int(exc.status)}): {exc}")
```

Constructor options: `pin_provider` (callable returning the PIN; without it an
unpaired call raises `NotPairedError`), `auto_start=False` (require an
already-running daemon), `socket_path` (override the daemon socket).

## Pairing

Pairing needs a 6-digit PIN that macOS displays, once per daemon lifetime.
A `pin_provider` callback handles it transparently; to drive it explicitly:

```python
from apwlib import Daemon

daemon = Daemon()
daemon.request_challenge()  # macOS shows a 6-digit PIN
paired = daemon.verify_challenge(input("PIN: "))  # blocks until settled
```

A pairing cannot outlive the daemon (the helper issues a fresh PIN per
handshake by design), so keeping the daemon alive is what keeps the PIN rare.

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

## Daemon control & diagnostics

Most programs never touch the daemon — the facade auto-starts and reuses it.
For explicit lifecycle control (a setup step, a health endpoint):

```python
from apwlib import Daemon
from apwlib.diagnostics import run_checks

daemon = Daemon()
daemon.start()      # no-op if already running; raises DaemonStartError if not ready
daemon.status()     # {"running": ..., "bridge": ..., "paired": ..., ...}
daemon.restart()    # replace a wedged daemon
daemon.stop()

for check in run_checks(daemon):  # what `apwcli doctor` renders
    print(check.key, check.ok, check.detail)
```

## Data model

Reads return dataclasses (`PasswordEntry`, `OTPEntry`):

```python
from apwlib import PasswordEntry

entry = PasswordEntry(username="me@example.com", domain="github.com", password="hunter2")
print(entry.username, entry.domain)
#> me@example.com github.com
```

`PasswordEntry.password` is `None` when the vault withholds it.

## Errors

Every failure raises `ApwError` (or a subclass — `SessionError`,
`DaemonNotRunningError`, `NotPairedError`, `DaemonStartError`, `ServerError`)
carrying a `Status`:

```python
from apwlib import SessionError

try:
    raise SessionError()
except SessionError as exc:
    print(int(exc.status))
    #> 9
```

## Examples

Runnable scripts, ordered by complexity, live in
[`examples/`](../../examples): reading entries, one-time codes, saving a
credential, and explicit daemon control. Run any with
`uv run python examples/<dir>/main.py`.

## How it works

The [design notes](../../docs/design/apwlib.md) cover the whole story: Apple's
helper and its kernel-enforced launch constraint, the SRP pairing and SMSG
encryption, and why a (headless) browser is involved at all. The full API
reference is generated from the source at
[michel-tricot.github.io/apwcli](https://michel-tricot.github.io/apwcli/reference/).

## License

MIT © Michel Tricot
