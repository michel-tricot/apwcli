# apwcli

`apwcli` is the command-line interface for [apwlib](apwlib.md) — access to Apple
Passwords (iCloud Keychain) from the terminal.

## Installation

```console
$ pip install apwcli
```

Requires macOS with the iCloud Passwords extension installed in a supported browser
(Chrome, Brave, Edge, or Chromium).

## Getting started

You don't start anything manually — any command auto-starts a managed headless browser in
the background (a singleton that persists across commands). The first data command even
pairs for you: it pops the macOS PIN dialog and prompts for the code. To pair explicitly:

```console
$ apwcli daemon pair
Enter the PIN shown by macOS: 123456
● paired
```

## Output formats

The password and OTP commands take `--format` / `-o` with three values (daemon commands
always print a status):

- `table` (default) — a pretty table, for humans.
- `json` — for scripts and agents.
- `text` — tab-separated values, no header, for piping into `cut`/`awk`/`grep`.

```console
$ apwcli pw list github.com                 # table (default)
╭──────────────────┬────────────┬──────────╮
│ username         │ domain     │ password │
├──────────────────┼────────────┼──────────┤
│ me@example.com   │ github.com │ hunter2  │
╰──────────────────┴────────────┴──────────╯

$ apwcli pw list github.com --format json
{"results": [{"username": "me@example.com", "domain": "github.com", "password": "hunter2"}], "status": 0}

$ apwcli pw get github.com me@example.com --format text | cut -f3
hunter2
```

## Passwords

```console
$ apwcli pw list github.com
$ apwcli pw get github.com me@example.com
$ apwcli pw save github.com me@example.com          # prompts for the password
$ printf 'correct horse' | apwcli pw save example.com me@example.com --stdin
```

## One-time codes

```console
$ apwcli otp get github.com
$ apwcli otp list github.com
```

## The daemon

Daemon management lives under `apwcli daemon`. You rarely need it — commands auto-start the
daemon — but you can inspect or control it:

```console
$ apwcli daemon status
● daemon     running
● extension  connected
● pairing    paired

$ apwcli daemon stop
$ apwcli daemon start          # pre-warm; --foreground to run attached for debugging
```

The daemon runs detached, so it keeps running after you close the terminal. You pair once
per daemon lifetime — keep the daemon up and the PIN stays rare. (Persisting a pairing
across a full restart isn't possible: the helper generates a fresh PIN for every
handshake by design — see the [design notes](design/apwlib.md).)

## Errors

Errors go to stderr and the process exits with the protocol status code (for example `9`
when the daemon is not running or not paired). With `--format json` the error is a JSON
object; otherwise it's a short `error: …` line.
