"""Execute and lint every Python code block in the documentation.

Any ```python block in docs/, the root README, or the apwlib README is run
for real; `#> ...` comments are checked against actual printed output. Run
`uv run pytest tests/test_docs.py --update-examples` to rewrite outputs after
an intentional behavior change.
"""

from pathlib import Path

import pytest
from pytest_examples import CodeExample, EvalExample, find_examples

ROOT = Path(__file__).parent.parent

DOC_SOURCES = [
    ROOT / "docs",
    ROOT / "README.md",
    ROOT / "packages" / "apwlib" / "README.md",
]


@pytest.mark.parametrize("example", list(find_examples(*DOC_SOURCES)), ids=str)
def test_docs_examples(example: CodeExample, eval_example: EvalExample) -> None:
    eval_example.set_config(line_length=100)
    if eval_example.update_examples:
        eval_example.format(example)
        eval_example.run_print_update(example)
    else:
        eval_example.lint(example)
        eval_example.run_print_check(example)
