#!/usr/bin/env python3
"""Market session state (pre-open/open/closed/holiday) in IST.

Thin wrapper around the shared `nsefno` package: `nsefno session ...`.
Works from the repo checkout, from a pip install, or from a packaged .skill
(where nsefno/ is vendored next to this script).
"""
import pathlib
import sys

_here = pathlib.Path(__file__).resolve()
for p in (_here.parent, *_here.parents[1:4]):
    if (p / "nsefno" / "__init__.py").exists():
        sys.path.insert(0, str(p))
        break

from nsefno.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["session", *sys.argv[1:]]))
