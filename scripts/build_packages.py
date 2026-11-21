#!/usr/bin/env python3
"""Build self-contained .skill archives (zip) for the Claude web app / any agent.

Each archive contains the skill folder at its root with the shared `nsefno` package
vendored into scripts/, so the scripts run without `pip install` (numpy, scipy, pyyaml,
requests still need to be available in the runtime).
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "skill-packages"
SKIP = {"__pycache__", ".pytest_cache"}


def _add_tree(z: zipfile.ZipFile, src: Path, arc_root: str) -> None:
    for p in sorted(src.rglob("*")):
        if p.is_file() and not any(part in SKIP for part in p.parts) and p.suffix != ".pyc":
            z.write(p, f"{arc_root}/{p.relative_to(src).as_posix()}")


def main() -> int:
    index = yaml.safe_load((ROOT / "skills-index.yaml").read_text())
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    for s in index["skills"]:
        name = s["id"]
        target = OUT / f"{name}.skill"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            _add_tree(z, ROOT / "skills" / name, name)
            _add_tree(z, ROOT / "nsefno", f"{name}/scripts/nsefno")
            z.write(ROOT / "DISCLAIMER.md", f"{name}/DISCLAIMER.md")
            z.write(ROOT / "LICENSE", f"{name}/LICENSE")
        print(f"built {target.relative_to(ROOT)} ({target.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
