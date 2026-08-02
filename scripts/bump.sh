#!/usr/bin/env bash
# Bump the lockstep version of apwcli and apwlib: both pyprojects plus the
# apwlib==X pin in the root, then refresh the lockfile.
# Usage: scripts/bump.sh 0.2.0
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
version="${1:?usage: scripts/bump.sh <version>}"

python3 - "$version" <<'PY'
import re
import sys
from pathlib import Path

version = sys.argv[1]
for path in ("pyproject.toml", "packages/apwlib/pyproject.toml"):
    p = Path(path)
    text, n = re.subn(r'^version = ".*"$', f'version = "{version}"', p.read_text(), count=1, flags=re.M)
    assert n == 1, f"no version line in {path}"
    p.write_text(text)

p = Path("pyproject.toml")
text, n = re.subn(r'"apwlib==[^"]*"', f'"apwlib=={version}"', p.read_text())
assert n == 1, "no apwlib== pin in pyproject.toml"
p.write_text(text)
print(f"version -> {version} (both pyprojects + the pin)")
PY

uv lock --quiet
echo "Now: scripts/check.sh, commit, then: git tag v$version && git push origin v$version"
