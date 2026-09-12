#!/usr/bin/env python3
"""Run the tests in `scripts/tests/`, and fail if there were none to run.

Why this exists rather than `python3 -m unittest discover` written straight into
the workflow: **discovery with nothing to discover exits 0.** `scripts/tests/`
held zero tracked files from 2026-08-27 to 2026-09-12 (`#104`) — the three test
modules were committed only on the unmerged branch `feat/8-provisioning-flow`,
and a `checkout` away from it removed them from the worktree, leaving a stale
`__pycache__` as the only evidence they had ever existed. Nothing went red:
there was no runner to go red. An empty suite and a passing suite are the same
colour, which is the failure this repo keeps paying for in other shapes.

So the count is asserted, not printed and trusted. Zero collected is exit 1 with
the reason.

Two details that are deliberate, both measured 2026-09-12:

1. **No `-t` / `--top-level-directory`.** `discover -s scripts/tests -t .` names
   the module `scripts.tests.test_*`, and `scripts/` has no `__init__.py`, so it
   dies with `ImportError: Start directory is not importable`. The tests find the
   repo root from `__file__`, never from the import path, so the bare form is the
   correct one — not a workaround.

2. **No floor above zero.** Asserting "at least 38" would go red on the first
   legitimate change to the suite, and a check that fires on correct input gets
   switched off (`~/.claude/CLAUDE.md`). Zero is the only count that cannot mean
   "someone edited the tests"; the number is printed so a drop stays visible.
"""

from __future__ import annotations

# A stale `.pyc` makes a negative control report the result of the PREVIOUS
# mutation (jgct#96: CPython accepts a cached .pyc when source mtime to the
# second AND size both match, which is exactly what a minimal edit looks like).
# Nothing here should ever write bytecode.
import sys

sys.dont_write_bytecode = True

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "scripts" / "tests"


def main() -> int:
    if not TESTS.is_dir():
        print(f"FAIL  {TESTS.relative_to(ROOT)}/ does not exist.")
        print("      It held the §3 tests until 2026-08-27 and its absence was")
        print("      silent for two weeks (#104). If the tests moved, point this")
        print("      runner at them; do not delete the assertion.")
        return 1

    suite = unittest.defaultTestLoader.discover(str(TESTS))
    count = suite.countTestCases()

    if count == 0:
        print(f"FAIL  0 tests collected from {TESTS.relative_to(ROOT)}/")
        print("      This is the #104 state: the directory is there and empty,")
        print("      and `unittest discover` exits 0 on it. A suite that runs")
        print("      nothing must not report the same colour as one that passes.")
        return 1

    print(f"collected {count} tests from {TESTS.relative_to(ROOT)}/", flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    if not result.wasSuccessful():
        print(f"::error::{len(result.failures)} failed, {len(result.errors)} errored "
              f"out of {count} collected")
        return 1

    print(f"ok — {count} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
