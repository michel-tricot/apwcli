# apwcli command reference

`apwcli` is the command-line interface for [apwlib](apwlib.md) — Apple
Passwords (iCloud Keychain) from the terminal.

```console
$ pip install apwcli
```

Requires macOS with a supported browser installed (Chrome, Brave, Edge, or
Chromium); the iCloud Passwords extension itself is downloaded automatically
from the Chrome Web Store. `apwcli --version` prints the
installed apwcli and apwlib versions.

## Getting started

Nothing to launch: any command auto-starts the managed daemon, and the first
data command pairs for you (pops the macOS PIN dialog and prompts for the
code). When stdin is not a terminal — scripts, agents, GUI apps — the prompt
is replaced by a small PIN window on screen; if the window is closed or
nobody answers, the command fails with status `9`. To pair explicitly:

```console
$ apwcli daemon pair
Enter the PIN shown by macOS: 123456
● paired
```

If anything misbehaves, `apwcli doctor` checks the whole chain and points at the
fix:

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

## Passwords

```console
$ apwcli pw list github.com                    # accounts for a site
$ apwcli pw get github.com me@example.com      # password entry (masked in the table)
$ apwcli pw get github.com me@example.com --show   # reveal in the table
$ apwcli pw get github.com me@example.com -c   # copy to clipboard, print nothing
$ apwcli pw save github.com me@example.com     # create/update (prompts)
$ printf 'correct horse' | apwcli pw save example.com me@example.com  # piped: reads stdin
$ apwcli pw generate github.com me@example.com # make a strong password and save it
$ apwcli pw generate github.com me@example.com -n 32 --no-symbols  # 32 chars, alnum only
```

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
$ apwcli otp list github.com       # accounts that have codes
```

## Output formats

Password and OTP commands take `--format` / `-o`:

- `table` (default) — a pretty table, for humans.
- `json` — `{"results": [...], "status": 0}`, for scripts and agents.
- `text` — tab-separated values, no header, for `cut`/`awk`/`grep`.

```console
$ apwcli pw list github.com --format json
{"results": [{"username": "me@example.com", "domain": "github.com"}], "status": 0}

$ apwcli pw get github.com me@example.com -o text | cut -f3
hunter2
```

## Daemon

Commands auto-start the daemon, so `apwcli daemon` is for inspection and
control, not routine use:

```console
$ apwcli daemon status
● daemon     running
● extension  connected
● pairing    paired

$ apwcli daemon pair             # (re)pair; --pin 123456 to skip the prompt
$ apwcli daemon stop             # stop the daemon and its browser
$ apwcli daemon restart          # replace a wedged daemon with a fresh one
$ apwcli daemon logs             # tail the log; -f to follow, --clear to wipe it
$ apwcli daemon start            # pre-warm; --foreground to run attached,
                                 # --browser to pick one (auto, chromium, chrome, brave, edge)
```

The log lives at `~/.apwlib/daemon.log` (records lifecycle and errors only, never
plaintext secrets) and is rotated to `daemon.log.1` once it passes ~1 MB.

The daemon runs detached and survives closing the terminal. Commands
auto-start a missing daemon; for anything else that looks off (e.g.
`extension disconnected` because its browser was killed), `apwcli daemon
restart` replaces it with a fresh one. Pairing lasts for the daemon's lifetime — keep it running and
the PIN stays rare. (A pairing cannot be persisted across restarts: the helper
generates a fresh PIN per handshake by design — see the
[design notes](design/apwlib.md).)

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

The server exposes `status`, `start_pairing`/`submit_pin`, `list_accounts`
(usernames only), `get_otp`, and `save_password`. Plaintext password reads are
excluded by default because MCP tool results travel to the model provider —
opt in by configuring the client to run `apwcli mcp run --allow-passwords`.

## Errors and exit codes

Errors print `error: …` to stderr (a JSON object with `-o json`) and the
process exits with the protocol status code — for example `9` when the daemon
is not running or the session is not paired, `1` on non-macOS platforms or when
no supported browser is installed (any command fails immediately in that case,
naming the browsers to install, rather than waiting on a daemon that can't
start).
