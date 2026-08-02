# apwcli

**Apple Passwords (iCloud Keychain) from the terminal — and from Python.**

Two packages, one repo:

- **`apwcli`** — the CLI: read passwords and one-time codes, save logins,
  script it all with JSON/TSV output.
- **`apwlib`** — the library underneath: a typed Python API over a managed
  background daemon.

## Why apwcli?

Apple brokers keychain access for third-party browsers through a helper that
only runs inside an approved browser — there is no public API. apwcli runs
that plumbing for you: a background daemon hosts the iCloud Passwords
extension in a headless browser, pairs with the macOS PIN once, and exposes
the vault to your terminal, your scripts, and your agents.

- **Passwords & one-time codes** — read, save, and update Apple Passwords entries
- **Agent-ready** — bundled Claude skill and MCP server (`apwcli mcp install`)
- **Safe by default** — passwords are masked on screen; `-c` copies to the clipboard instead
- **Scriptable** — JSON/TSV output everywhere; Python API via `apwlib`
- **Zero setup** — the daemon auto-starts on first use and pairs on demand

## Install

```sh
brew install michel-tricot/tap/apwcli   # or: uv tool install apwcli, pipx install apwcli
```

For the library only:

```sh
uv add apwlib             # or: pip install apwlib
```

Requires macOS with a supported browser installed (Chrome, Brave, Edge, or
Chromium); the iCloud Passwords extension itself is downloaded automatically
from the Chrome Web Store.

## Quickstart

```sh
apwcli pw get github.com                 # saved entries (passwords masked)
apwcli pw get github.com me@example.com -c   # copy one password to the clipboard
apwcli otp get github.com                # current one-time code
```

The first command sets everything up: it starts the daemon and, if needed,
walks you through the one-time PIN pairing. From Python:

```python
from apwlib import ApplePasswords

pw = ApplePasswords(pin_provider=lambda: input("PIN: "))
for entry in pw.get_password("github.com"):
    print(entry.username)
```

## Where next

- [CLI reference](apwcli.md) — every command, output formats, exit codes
- [Library guide](apwlib.md) — the `ApplePasswords` facade, pairing, errors
- [API reference](reference.md) — the full public API, from the source
- [How it works](design/apwlib.md) — the helper protocol and the daemon design
