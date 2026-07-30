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


# Blocks containing this marker are lint-checked and formatted like the rest, but not
# executed: they call the facade, which needs a running daemon + a paired browser.
_NEEDS_DAEMON = "needs a running daemon"


@pytest.mark.parametrize("example", list(find_examples(*DOC_SOURCES)), ids=str)
def test_docs_examples(example: CodeExample, eval_example: EvalExample) -> None:
    eval_example.set_config(line_length=100)
    executable = _NEEDS_DAEMON not in example.source
    if eval_example.update_examples:
        eval_example.format(example)
        if executable:
            eval_example.run_print_update(example)
    else:
        eval_example.lint(example)
        if executable:
            eval_example.run_print_check(example)
