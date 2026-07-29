# apwcli

Command-line interface for [apwlib](packages/apwlib).

```console
$ apwcli greet world
Hello, world!
```

See [docs/apwcli.md](docs/apwcli.md) for usage and [docs/apwlib.md](docs/apwlib.md) for
the underlying library.

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
$ uv run apwcli greet world      # run the CLI
$ uv run pytest                  # run all tests
$ uv run ruff format .           # format
$ uv run ruff check --fix .      # lint and autofix
$ uv run ty check                # typecheck
$ uv build --all-packages        # build both wheels/sdists into dist/
```

After an intentional behavior change, refresh doc example outputs with
`uv run pytest tests/test_docs.py --update-examples`.
