# apwcli

Command-line access to Apple Passwords (iCloud Keychain) on macOS, built on
[apwlib](packages/apwlib).

```console
$ apwcli daemon pair                       # pair once with the macOS PIN
$ apwcli pw get github.com me@example.com  # read a password
```

macOS only lets an approved browser reach the Apple Passwords helper, so the first command
auto-starts a headless browser in the background (a singleton that survives closing the
terminal) and pairs on demand — you never launch or supervise anything.

**Requirements:** macOS with the iCloud Passwords extension installed in a supported
browser (Chrome, Brave, Edge, or Chromium).

## Usage

Passwords and one-time codes — these accept `--format text|json|table` (`table` default;
`text` is TSV for piping, `json` for scripts/agents):

```console
$ apwcli pw list github.com                          # accounts for a site
$ apwcli pw get github.com me@example.com            # the password
$ apwcli pw save github.com me@example.com           # create/update (prompts)
$ apwcli otp get github.com                          # one-time code
$ apwcli pw get github.com me@example.com -o text    # just the fields, tab-separated
```

Daemon and pairing:

```console
$ apwcli daemon status     # daemon / extension / pairing state
$ apwcli daemon pair       # (re)pair with the macOS PIN
$ apwcli daemon stop       # stop the daemon and its browser
```

See [docs/apwcli.md](docs/apwcli.md) for the full guide and
[docs/design/apwlib.md](docs/design/apwlib.md) for how it works and why a browser is
required.

## Repository layout

This repository is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
publishing two packages:

- **`apwcli`** — this top-level project (`src/apwcli`), the CLI.
- **`apwlib`** — the core library, in [`packages/apwlib`](packages/apwlib).

Documentation lives in [`docs/`](docs). Python code blocks in the docs and READMEs are
executed as part of the test suite, so examples cannot go stale.

## Development

```console
$ uv sync
```

There are no git hooks: validation before commit/push is the responsibility of whoever
(or whatever agent — see [AGENTS.md](AGENTS.md)) makes the change, by running:

```console
$ scripts/check.sh
```

which validates:

- **format** — `uv run ruff format --check .`
- **lint** — `uv run ruff check .`
- **typecheck** — `uv run ty check`
- **tests** — `uv run pytest` (includes executing all Python code blocks in the docs)

Code changes must ship with matching doc updates, and implementation decisions belong in
`docs/` (see AGENTS.md). CI runs the same suite on every push and pull request.

## Common commands

```console
$ uv run apwcli pw list github.com   # run the CLI
$ uv run pytest                      # run all tests
$ uv run ruff format .               # format
$ uv run ruff check --fix .          # lint and autofix
$ uv run ty check                    # typecheck
$ uv build --all-packages            # build both wheels/sdists into dist/
```

After an intentional behavior change, refresh doc example outputs with
`uv run pytest tests/test_docs.py --update-examples`.
