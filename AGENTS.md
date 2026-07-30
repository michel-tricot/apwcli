# Agent instructions

This is a uv workspace with two publishable packages:

- `apwcli` — the CLI. The top-level `pyproject.toml` is both the workspace root AND
  this package's manifest; its code is in `src/apwcli`, tests in `tests/`. The CLI
  is the `src/apwcli/cli/` package — `common.py` holds the shared Typer apps and
  helpers, and each command group has its own module (`passwords.py`, `otp.py`,
  `daemon.py`, `skills.py`, `mcp.py`) — mirroring bearcli's layout. The MCP server
  lives in `src/apwcli/mcpserver.py`, and the bundled agent skill (shipped as
  package data) in `src/apwcli/skills/`.
- `packages/apwlib` — the core library; `apwcli` depends on it via a workspace source.

The top-level `pyproject.toml` also holds the dev dependency group and ALL tool
configuration.

## Validation — required before every commit and push

There are deliberately no git hooks in this repo. You (the agent) are the gate:
before committing or pushing, run the full suite and make sure it passes:

```console
$ scripts/check.sh
```

This runs, in order:

1. `uv run ruff format --check .` — formatting
2. `uv run ruff check .` — lint
3. `uv run ty check` — typecheck
4. `uv run pytest` — unit tests + execution of every Python code block in the docs

Never commit or push with a failing check. Fix the code (or the docs) rather than
weakening the check. CI (`.github/workflows/ci.yml`) runs the same suite on every
push and pull request, so anything skipped locally will fail there.

## Documentation rules

- **Code changes require doc changes.** If you touch anything under `src/` or
  `packages/apwlib/src/`, update `docs/` and/or the relevant README in the same change
  (only skip when the change genuinely has no user-visible effect, and say so). There
  is no script enforcing this — you are responsible for it.
- **Doc code is executable.** Every ` ```python ` block in `docs/` and the READMEs is
  run and lint-checked by `tests/test_docs.py` (pytest-examples). Expected output is
  written as `#> ...` comments and verified against actual output. After an
  intentional behavior change, refresh outputs with:
  `uv run pytest tests/test_docs.py --update-examples`.

## Tool configuration rules

- All ruff / ty / pytest configuration lives in the root `pyproject.toml` only.
  Never add `[tool.ruff]`, `[tool.ty]`, or `[tool.pytest.ini_options]` to a package's
  `pyproject.toml`, and never add standalone `ruff.toml` / `ty.toml` files — ruff uses
  nearest-config-wins, so a package-level section would silently fork the settings.
- Markdown files are excluded from ruff on purpose: doc code blocks use the
  pytest-examples `#>` output convention, which ruff's markdown formatter mangles.
  Doc examples are still linted, via `tests/test_docs.py`.

## Common commands

```console
$ uv sync                        # install/refresh the workspace
$ uv run apwcli pw list github.com   # run the CLI
$ uv run ruff format .           # format
$ uv run ruff check --fix .      # lint with autofix
$ uv build --all-packages        # build both wheels/sdists into dist/
```
