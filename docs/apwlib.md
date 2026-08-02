# apwlib library reference

`apwlib` is programmatic access to Apple Passwords (iCloud Keychain) on macOS —
the library behind [`apwcli`](apwcli.md).

```console
$ pip install apwlib
```

## The facade

All access goes through `ApplePasswords`. The background daemon is
auto-managed (first call starts it, detached and reused); with a
`pin_provider`, pairing happens on demand too:

```python
from apwlib import ApplePasswords

pw = ApplePasswords(pin_provider=lambda: input("PIN: "))

pw.get_login_names("github.com")  # accounts for a site -> list[PasswordEntry]
pw.get_password("github.com", "me@example.com")  # -> list[PasswordEntry]
pw.save_account("example.com", "me@example.com", "s3cret")  # create/update
pw.list_otp("github.com")  # accounts with codes -> list[OTPEntry]
pw.get_otp("github.com")  # the current code(s) -> list[OTPEntry]
```

Reads are keyed to a URL and matched by registrable domain; an empty list
means no results. `pw.daemon` gives explicit control: `start()`, `stop()`,
`status()`, and the pairing primitives `request_challenge()` and
`verify_challenge(pin)` (blocks until pairing settles; True once paired).

Constructor options: `pin_provider` (callable returning the PIN; without it an
unpaired call raises `NotPairedError`), `auto_start=False` (require an
already-running daemon), `socket_path` (override the daemon socket).

## Entries are typed

Results are dataclasses. `from_raw` shows the shape without a daemon:

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

Every failure raises an `ApwError` (or a subclass) carrying a `Status`:

```python
from apwlib import SessionError, Status

try:
    raise SessionError(Status.INVALID_SESSION)
except SessionError as exc:
    print(int(exc.status))
    #> 9
```

The hierarchy: `SessionError` covers session problems, refined into
`DaemonNotRunningError` (socket unreachable) and `NotPairedError` (daemon up,
session unpaired); `ServerError` covers malformed daemon responses. Catch
`SessionError` to re-pair, `ApwError` for everything else.

Python code blocks in this file are executed and lint-checked on every test
run. For architecture and protocol details, see the
[design notes](design/apwlib.md).
