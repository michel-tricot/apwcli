<div align="center">

# 🔑 `apwcli`

**Apple Passwords (iCloud Keychain) from the terminal.**
Read passwords and one-time codes, save logins, script it all.

[![CI](https://github.com/michel-tricot/apwcli/actions/workflows/ci.yml/badge.svg)](https://github.com/michel-tricot/apwcli/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](#)

[**Website**](https://michel-tricot.github.io/apwcli/) ·
[Commands](docs/apwcli.md) ·
[Python library](packages/apwlib) ·
[Examples](examples) ·
[How it works](docs/design/apwlib.md)

</div>

---

- **Passwords & one-time codes** — read, save, and update Apple Passwords entries
- ✨ **Agent-ready** — bundled Claude skill and MCP server (`apwcli mcp install`)
- **Safe by default** — passwords are masked on screen; `-c` copies to the clipboard instead
- **Scriptable** — JSON/TSV output everywhere; Python API via [`apwlib`](packages/apwlib)
- **Zero setup** — a background daemon auto-starts on first use and pairs on demand

## Install

```sh
brew install michel-tricot/tap/apwcli   # or: uv tool install apwcli, pipx install apwcli
```

Or from a clone: `uv sync`, then `uv run apwcli --help`.

Requires macOS with a supported browser installed (Chrome, Brave, Edge, or
Chromium); the iCloud Passwords extension itself is downloaded automatically
from the Chrome Web Store.

## Quick start

```sh
apwcli pw get github.com                 # saved entries (passwords masked)
apwcli pw get github.com me@example.com  # narrow to one account
apwcli otp get github.com                # current one-time code
```

The first command sets everything up: it starts the daemon and, if needed,
pairs — macOS shows a 6-digit PIN, apwcli prompts for it, and you're set for
as long as the daemon runs.

Something not working? `apwcli doctor` checks the whole chain — browser,
extension, daemon, pairing — and tells you what to fix.

## Security

This is a tool for your passwords, so here's exactly what it does with them:

- **Nothing leaves your Mac.** apwcli talks only to Apple's local iCloud
  Passwords helper, through the official extension running in a browser on your
  machine. There are no servers, telemetry, or network calls of our own.
- **Apple's crypto does the crypto.** Pairing (SRP) and per-command encryption
  (AES-GCM) run inside the real extension; apwcli is transport around it and
  never implements or handles key material itself.
- **Secrets stay off your screen and out of scrollback.** Tables mask passwords
  by default (`--show` to reveal); `text`/`json` output is unmasked for piping.
  `-c` copies to the clipboard instead of printing, and the clipboard is
  auto-cleared after 20s (`--clear-after`).
- **Agents never see plaintext passwords by default.** The MCP server exposes
  one-time codes, saving, and pairing — but not password reads unless you
  explicitly run it with `--allow-passwords` (MCP results travel to the model
  provider).
- **Nothing sensitive is logged.** The daemon log records lifecycle and errors
  only; command bodies are encrypted inside the browser and never written in
  plaintext.

Full details — the launch constraint, the pairing handshake, the threat model —
are in the [design notes](docs/design/apwlib.md). Found a vulnerability? See
[SECURITY.md](SECURITY.md).

## Commands

### Passwords

```sh
apwcli pw get github.com                      # entries for a site, passwords masked
apwcli pw get github.com me@example.com       # narrow to one account
apwcli pw get github.com me@example.com -c    # copy to clipboard, print nothing
apwcli pw get github.com me@example.com --show   # reveal in the table
apwcli pw save github.com me@example.com      # create/update (prompts)
printf '%s' "$PW" | apwcli pw save github.com me@example.com   # piped: no prompt
apwcli pw generate github.com me@example.com  # make a strong password and save it
apwcli pw generate github.com me@example.com -c   # …and copy it, don't print
```

Sites match by registrable domain: `github.com`, `https://gist.github.com/x`,
and `www.github.com` all find the same accounts. Clipboard copies (`-c`) are
wiped after 20 seconds; tune it with `--clear-after` (`0` keeps them).

### One-time codes

```sh
apwcli otp get github.com        # the current code
apwcli otp get github.com -c     # straight to the clipboard
apwcli otp list github.com       # accounts that have codes
```

### Scripting

Data commands take `--format` / `-o`: `table` (default), `json`, or `text`
(TSV for piping). Pipes always carry the real values — masking is only for
tables on screen.

```sh
apwcli pw get github.com me@example.com -o text | cut -f3
apwcli otp get github.com -o json | jq -r '.results[0].code'
```

Errors exit with the protocol status code (`9` = daemon down or not paired)
and print `error: …` to stderr, or a JSON object with `-o json`.

### Daemon & pairing

Commands auto-start a background daemon on first use and pair on demand — an
unpaired command pops the macOS PIN dialog and prompts for the code, so you
never launch or supervise anything. Without a terminal (scripts, agents, GUI
apps), the prompt becomes a small on-screen PIN window instead. A pairing
lasts for the daemon's lifetime; keeping the daemon running keeps the PIN
rare.

```sh
apwcli doctor           # diagnose the whole setup (browser, extension, pairing)
apwcli daemon status    # daemon / extension / pairing state
apwcli daemon pair      # pair explicitly; --pin 123456 to skip the prompt
apwcli daemon restart   # replace a wedged daemon with a fresh one
apwcli daemon logs      # tail the daemon log (-f to follow, --clear to wipe)
apwcli daemon stop      # stop the daemon and its browser
```

## Agents

apwcli ships with integrations for AI agents:

```sh
apwcli skills install          # install the Claude skill into ~/.claude/skills
apwcli mcp install             # wire the MCP server into Claude, Cursor, VS Code, …
```

The MCP server exposes one-time codes, saving, and pairing —
**never plaintext passwords** unless you start it with
`apwcli mcp run --allow-passwords` (MCP tool results travel to the model
provider; see the [design notes](docs/design/apwlib.md)).

## Library

[`apwlib`](packages/apwlib) is the Python API behind the CLI:

```python
from apwlib import ApplePasswords

pw = ApplePasswords(pin_provider=lambda: input("PIN: "))
for entry in pw.get_password("github.com", "me@example.com"):
    login(entry.username, entry.password)  # typed entries; nothing printed
```

Full guide and API reference on the
[website](https://michel-tricot.github.io/apwcli/); runnable scripts in
[`examples/`](examples).

## Contributing

Contributions are welcome. The repository is a
[uv](https://docs.astral.sh/uv/) workspace with two packages: `apwcli` (this
project, `src/apwcli`) and [`apwlib`](packages/apwlib). Set up a checkout:

```sh
git clone https://github.com/michel-tricot/apwcli
cd apwcli
uv sync
```

Before committing, run the full validation suite — format, lint, typecheck,
tests — and keep it green; CI runs the same thing:

```sh
scripts/check.sh
```

Work on the documentation site (MkDocs Material):

```sh
uv sync --group docs
uv run mkdocs serve      # live preview at http://127.0.0.1:8000
```

Contributor and agent guidelines live in [AGENTS.md](AGENTS.md); design notes
in [docs/design/apwlib.md](docs/design/apwlib.md).

## License

MIT © Michel Tricot · Not affiliated with Apple. Apple Passwords and iCloud
Keychain are trademarks of Apple Inc.
