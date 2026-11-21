#!/usr/bin/env python3
"""Dry-run order payloads with SEBI/exchange guardrails; confirmed send only.

Thin wrapper around the shared `nsefno` package: `nsefno order ...`.
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
    sys.exit(main(["order", *sys.argv[1:]]))
