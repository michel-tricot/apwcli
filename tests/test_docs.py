"""Execute and lint every Python code block in the shipping documentation.

Any ```python block in the files listed below is run for real; `#> ...` comments
are checked against actual printed output. Run
`uv run pytest tests/test_docs.py --update-examples` to rewrite outputs after
an intentional behavior change.

Design/planning notes under docs/design/ are intentionally excluded: they
describe not-yet-built APIs, so their code is illustrative, not executable.
"""

from pathlib import Path

import pytest
from pytest_examples import CodeExample, EvalExample, find_examples

ROOT = Path(__file__).parent.parent

DOC_SOURCES = [
    ROOT / "docs" / "apwcli.md",
    ROOT / "docs" / "apwlib.md",
    ROOT / "README.md",
    ROOT / "packages" / "apwlib" / "README.md",
]


def _needs_daemon(source: str) -> bool:
    """Blocks that build the ApplePasswords facade need a running daemon + paired browser.

    They're lint-checked and formatted like the rest, but not executed. Detected by
    content so the docs carry no test-only markers for readers to trip over.
    """
    return "ApplePasswords(" in source


@pytest.mark.parametrize("example", list(find_examples(*DOC_SOURCES)), ids=str)
def test_docs_examples(example: CodeExample, eval_example: EvalExample) -> None:
    # Doc examples print their output by design (the `#> ...` convention), so T201
    # doesn't apply to them even though the project lints against stray prints.
    eval_example.set_config(line_length=100, ruff_ignore=["T201"])
    executable = not _needs_daemon(example.source)
    if eval_example.update_examples:
        eval_example.format(example)
        if executable:
            eval_example.run_print_update(example)
    else:
        eval_example.lint(example)
        if executable:
            eval_example.run_print_check(example)
