#!/usr/bin/env python3
"""Run the repository's standard-library regression suite."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if result.wasSuccessful():
        print("self-check: PASS (ephemeral fixtures removed)")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
