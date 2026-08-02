---
name: apple-passwords
description: Read and save Apple Passwords (iCloud Keychain) credentials and one-time codes with the apwcli CLI. Use when the user asks for a saved password or 2FA/OTP code, wants to save or update a login, or asks anything about their Apple Passwords / iCloud Keychain.
---

# Apple Passwords via apwcli

apwcli reads and writes Apple Passwords through a background daemon it manages
itself — never start or supervise anything. Requires macOS. If `apwcli` is not
on PATH (command not found), ask the user before installing it:
`uv tool install apwcli` (or `pipx install apwcli`).

## Pairing (needed once per daemon lifetime)

If a command exits with code 9 and mentions pairing, macOS must show the user a
6-digit PIN. **The PIN appears in a dialog on the user's screen — you cannot
read it.** Run:

- `apwcli daemon pair` — pops the dialog and prompts; in a non-interactive
  shell, ask the user for the PIN first and pass it: `apwcli daemon pair --pin 123456`.
- `apwcli daemon status` — daemon / extension / pairing state.

## Reading

Always use machine-readable output instead of parsing tables:

- `apwcli pw get <url> [username] -o json` — password entries for a site.
  URLs match by registrable domain: `github.com`, a full URL, or a subdomain
  all hit the same entries. There is no list-everything command — every read
  needs a URL. `-o text` is TSV for piping.
- `apwcli otp get <url> -o json` — the current one-time code (for 2FA
  prompts). `apwcli otp list <url> -o json` shows which accounts have codes.

## Secrets — important

Never print a password into the conversation unless the user explicitly asks
to see it. Prefer routes where the value bypasses you and the transcript:

- `apwcli pw get <url> <username> -c` — copies the password to the user's
  clipboard and prints only a confirmation.
- Pipe directly to the consumer: `apwcli pw get <url> <user> -o text | cut -f3 | some-login-tool`.

One-time codes are fine to read and relay — they expire in seconds.

## Writing

- `printf '%s' "$PASSWORD" | apwcli pw save <url> <username> --stdin` — create
  or update a credential. Without `--stdin` it prompts interactively.
- Saving overwrites any existing password for that account: confirm with the
  user before updating a credential you did not just create.

## Limits

- Exit codes are protocol statuses: `9` means daemon down or not paired (see
  Pairing above); errors print an `error: …` line on stderr, or a JSON object
  with `-o json`.
- `apwcli --version` prints the installed version.
- `apwcli mcp run` is an MCP server (stdio) for AI apps; `apwcli mcp install
  <client>` configures a client. Neither is something to launch from a shell task.
- This skill ships with the CLI: `apwcli skills install` refreshes the copy in
  `~/.claude/skills/` after an upgrade. If commands here disagree with the
  installed CLI, trust `--help`.
