# Agent instructions

This is a uv workspace with two publishable packages:

- `apwcli` — the CLI. The top-level `pyproject.toml` is both the workspace root AND
  this package's manifest; its code is in `src/apwcli`, tests in `tests/`. The CLI
  is the `src/apwcli/cli/` package — `common.py` holds the shared Typer apps and
  helpers, and each command group has its own module (`passwords.py`, `otp.py`,
  `daemon.py`, `skills.py`, `mcp.py`, plus the top-level `doctor.py`).
  `_clipboard.py` is the detached clipboard-auto-clear helper. The MCP server
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
4. `uv run pytest` — unit tests

Never commit or push with a failing check. Fix the code (or the docs) rather than
weakening the check. CI (`.github/workflows/ci.yml`) runs the same suite on every
push and pull request, so anything skipped locally will fail there.

## Documentation rules

- **Code changes require doc changes.** If you touch anything under `src/` or
  `packages/apwlib/src/`, update `docs/` and/or the relevant README in the same change
  (only skip when the change genuinely has no user-visible effect, and say so). There
  is no script enforcing this — you are responsible for it. Doc code blocks are not
  executed by the test suite, so verify examples by hand when you change an API they
  use (the `#> ...` comments show expected output).

## Tool configuration rules

- All ruff / ty / pytest configuration lives in the root `pyproject.toml` only.
  Never add `[tool.ruff]`, `[tool.ty]`, or `[tool.pytest.ini_options]` to a package's
  `pyproject.toml`, and never add standalone `ruff.toml` / `ty.toml` files — ruff uses
  nearest-config-wins, so a package-level section would silently fork the settings.
- Markdown files are excluded from ruff on purpose: doc code blocks use the
  `#> ...` expected-output convention, which ruff's markdown formatter mangles.

## Documentation site

`mkdocs.yml` builds a Material for MkDocs site from `docs/` (Home, CLI
reference, library guide, mkdocstrings API reference, design notes). It is
deployed to GitHub Pages by `.github/workflows/docs.yml` on every push to
main. Build it locally with:

```console
$ uv sync --group docs
$ uv run mkdocs build --strict   # or: mkdocs serve
```

`--strict` fails on broken links; keep it passing. The API reference is
generated from docstrings — keep docstrings in plain Markdown (backtick code
spans, no reST roles), since mkdocstrings renders them verbatim.

## Releasing

`apwcli` and `apwlib` are published to PyPI **in lockstep**: one version for
both, and the root `pyproject.toml` pins `apwlib==<version>`. To cut a release:

```console
$ scripts/bump.sh 0.2.0      # both pyprojects + the pin + uv.lock
$ scripts/check.sh
$ git commit -am "Release 0.2.0" && git push
$ git tag v0.2.0 && git push origin v0.2.0
```

The tag triggers `.github/workflows/release.yml`, which verifies the lockstep
versions match the tag, builds both packages (`uv build --all-packages`),
publishes them to PyPI via Trusted Publishing (OIDC — no tokens stored), and
creates the GitHub release with generated notes and the artifacts attached.

One-time setup: on PyPI, add a trusted publisher for **both** project names
(`apwcli` and `apwlib`): owner `michel-tricot`, repository `apwcli`, workflow
`release.yml`. Before the first release, register them as *pending*
publishers (pypi.org → Publishing) so the names are claimed by the workflow.

## Common commands

```console
$ uv sync                        # install/refresh the workspace
$ uv run apwcli pw get github.com    # run the CLI
$ uv run ruff format .           # format
$ uv run ruff check --fix .      # lint with autofix
$ uv build --all-packages        # build both wheels/sdists into dist/
```
