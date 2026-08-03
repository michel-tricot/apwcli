# apwlib library reference

`apwlib` is programmatic access to Apple Passwords (iCloud Keychain) on macOS —
the library behind [`apwcli`](apwcli.md).

```console
$ uv add apwlib   # or: pip install apwlib
```

## The facade

All access goes through `ApplePasswords`. The background daemon is
auto-managed (first call starts it, detached and reused); with a
`pin_provider`, pairing happens on demand too:

```python
from apwlib import ApplePasswords

pw = ApplePasswords(pin_provider=lambda: input("PIN: "))

pw.get_password("github.com")  # entries for a site -> list[PasswordEntry]
pw.get_password("github.com", "me@example.com")  # narrow to one account
pw.save_password("example.com", "me@example.com", "s3cret")  # create/update
pw.list_otp("github.com")  # accounts with codes -> list[OTPEntry]
pw.get_otp("github.com")  # the current code(s) -> list[OTPEntry]
```

Reads are keyed to a URL and matched by registrable domain; an empty list
means no results. The `Daemon` class gives explicit lifecycle control:
`start()`, `stop()`, `restart()`, `status()`, and the pairing primitives
`request_challenge()` and `verify_challenge(pin)` (blocks until pairing
settles; True once paired). `start()`/`restart()` raise `DaemonStartError`
if the daemon does not come up.

Constructor options: `pin_provider` (callable returning the PIN; without it an
unpaired call raises `NotPairedError`), `auto_start=False` (require an
already-running daemon), `socket_path` (override the daemon socket).

## Entries are typed

Results are dataclasses:

```python
from apwlib import PasswordEntry

entry = PasswordEntry(username="me@example.com", domain="github.com", password="hunter2")
print(entry.username, entry.domain, entry.password)
#> me@example.com github.com hunter2
```

`PasswordEntry.password` is `None` when the vault withholds it.

## Errors

Every failure raises an `ApwError` (or a subclass) carrying a `Status`:

```python
from apwlib import SessionError

try:
    raise SessionError()
except SessionError as exc:
    print(int(exc.status))
    #> 9
```

The hierarchy: `SessionError` covers session problems, refined into
`DaemonNotRunningError` (socket unreachable) and `NotPairedError` (daemon up,
session unpaired); `DaemonStartError` means a spawned daemon never became
ready; `ServerError` covers malformed daemon responses. Catch `SessionError`
to re-pair, `ApwError` for everything else.

For architecture and protocol details, see the
[design notes](design/apwlib.md).
