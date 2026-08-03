# apwcli command reference

`apwcli` is the command-line interface for [apwlib](apwlib.md) — Apple
Passwords (iCloud Keychain) from the terminal.

```console
$ brew install michel-tricot/tap/apwcli   # or: uv tool install apwcli, pipx install apwcli
```

Requires macOS with a supported browser installed (Chrome, Brave, Edge, or
Chromium); the iCloud Passwords extension itself is downloaded automatically
from the Chrome Web Store. `apwcli --version` prints the installed apwcli and
apwlib versions.

## Getting started

Nothing to launch or configure — run a command:

```console
$ apwcli pw get github.com
```

The first data command sets everything up. If pairing is needed, macOS shows
a 6-digit PIN and apwcli prompts for it; when stdin is not a terminal —
scripts, agents, GUI apps — the prompt is replaced by a small PIN window on
screen. If the window is closed or nobody answers, the command fails with
status `9`. Anything misbehaving? See
[Troubleshooting](#troubleshooting).

## Passwords

```console
$ apwcli pw get github.com                     # entries for a site (passwords masked)
$ apwcli pw get github.com me@example.com      # narrow to one account
$ apwcli pw get github.com me@example.com --show   # reveal in the table
$ apwcli pw get github.com me@example.com -c   # copy to clipboard, print nothing
$ apwcli pw save github.com me@example.com     # create/update (prompts)
$ printf 'correct horse' | apwcli pw save example.com me@example.com  # piped: reads stdin
$ apwcli pw generate github.com me@example.com # make a strong password and save it
$ apwcli pw generate github.com me@example.com -n 32 --no-symbols  # 32 chars, alnum only
```

Sites match by registrable domain: `github.com`, `https://gist.github.com/x`,
and `www.github.com` all find the same accounts.

Tables mask passwords (`••••••••`) so they stay out of terminal scrollback;
`--show` reveals them, and `text`/`json` output always carries the real values.
`-c` requires the match to be unique — narrow with a username if a site has
several accounts, and copies are cleared from the clipboard after 20s
(`--clear-after N`, `0` to keep). `pw generate` saves the new password without
printing it; add `--show` to reveal it or `-c` to copy it.

## One-time codes

```console
$ apwcli otp get github.com        # the current code
$ apwcli otp get github.com -c     # copy it to the clipboard
$ apwcli otp get github.com me@example.com -c  # narrow by username first
$ apwcli otp list github.com       # accounts that have codes
```

## Output formats

Password and OTP commands take `--format` / `-o`:

- `table` (default) — a pretty table, for humans.
- `json` — `{"results": [...], "status": 0}`, for scripts and agents.
- `text` — tab-separated values, no header, for `cut`/`awk`/`grep`.

```console
$ apwcli otp list github.com --format json
{"results": [{"username": "me@example.com", "domain": "github.com"}], "status": 0}

$ apwcli pw get github.com me@example.com -o text | cut -f3
hunter2
```

## Agents

### Claude skill

```console
$ apwcli skills install          # copy the bundled skill into ~/.claude/skills
$ apwcli skills list             # what ships with this version
$ apwcli skills show             # print the skill's SKILL.md
```

Re-run `skills install` after upgrading apwcli to refresh the copy.

### MCP server

```console
$ apwcli mcp install             # configure a client (interactive picker)
$ apwcli mcp install claude-code # or name one: claude-desktop, cursor, vscode,
                                 # windsurf, gemini-cli, zed, codex
$ apwcli mcp run                 # the stdio server itself (clients start this)
```

The server exposes `status`, `start_pairing`/`submit_pin`, `get_otp`, and
`save_password`. Plaintext password reads are
excluded by default because MCP tool results travel to the model provider —
opt in by configuring the client to run `apwcli mcp run --allow-passwords`.

## Errors and exit codes

Errors print `error: …` to stderr (a JSON object with `-o json`) and the
process exits with the protocol status code — for example `9` when the
session is not paired or nothing answers, `1` on non-macOS platforms or when
no supported browser is installed (any command fails immediately in that
case, naming the browsers to install).

## Troubleshooting

Under the hood, commands are served by a background daemon that hosts the
iCloud Passwords extension; it starts on first use, runs detached, and
survives closing the terminal. A pairing lasts for the daemon's lifetime —
keep it running and the PIN stays rare. (A pairing cannot be persisted across
restarts: Apple's helper generates a fresh PIN per handshake by design — see
the [design notes](design/apwlib.md).)

If something misbehaves, start with `doctor` — it checks the whole chain and
points at the fix (`--json` for a machine-readable report):

```console
$ apwcli doctor
● browser      Brave, Google Chrome
● apple helper installed
● extension    v3.3.0 (downloaded)
● daemon       running
● bridge       connected — Brave (pid 41911)
● pairing      paired
```

The `browser` line lists the supported browsers installed; the `bridge` line
names the one the daemon is actually running (with its pid). `apple helper` is
Apple's password helper (the native-messaging integration) that lets the
extension reach the keychain — "installed" means macOS has it wired up. The
`extension` line shows the cached Chrome Web Store download (refreshed on
daemon start; `downloads on daemon start` before the first run).

The `daemon` group inspects and controls the background service:

```console
$ apwcli daemon status           # daemon / extension / pairing state (--json for scripts)
$ apwcli daemon pair             # (re)pair; --pin 123456 to skip the prompt
$ apwcli daemon restart          # replace a wedged daemon with a fresh one
$ apwcli daemon logs             # tail the log; -f to follow, --clear to wipe it
$ apwcli daemon stop             # stop the daemon and its browser
$ apwcli daemon start            # pre-warm; --foreground to run attached,
                                 # --browser to pick one for this daemon
                                 # (auto, chromium, chrome, brave, edge)
```

`--browser` applies to that daemon only (set a permanent default with the
`browser` key in `~/.apwlib/config.json`). The log lives at
`~/.apwlib/daemon.log` (records lifecycle and errors only, never plaintext
secrets) and is rotated to `daemon.log.1` once it passes ~1 MB. The most
common fix is simply `apwcli daemon restart` — e.g. when doctor reports
`extension disconnected` because the daemon's browser was killed.
