# apwlib examples

Small, runnable scripts showing the [`apwlib`](../packages/apwlib) public API,
ordered by complexity. Run them from the repo root with
`uv run python examples/<dir>/main.py` (or from anywhere once `apwlib` is
installed).

| # | Example | Shows |
| --- | --- | --- |
| 1 | [read-passwords](01-read-passwords/main.py) | `list_accounts` + `get_password`, transparent pairing via `pin_provider`, error handling |
| 2 | [one-time-codes](02-one-time-codes/main.py) | `list_otp` (who has codes) and `get_otp` (the current codes) |
| 3 | [save-password](03-save-password/main.py) | `save_password`, prompting for the secret instead of passing it on argv |
| 4 | [daemon-and-diagnostics](04-daemon-and-diagnostics/main.py) | explicit `Daemon` lifecycle, `apwlib.diagnostics.run_checks`, manual pairing |

All of them need macOS with a supported browser installed; the first run
starts the background daemon and pairs with a one-time PIN that macOS
displays. The public API is the `apwlib` package root plus `apwlib.pinwindow`
and `apwlib.diagnostics` — the full reference lives in
[docs/apwlib.md](../docs/apwlib.md).
