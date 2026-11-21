#!/usr/bin/env python3
"""Validate skills-index.yaml against skills/*/SKILL.md (Agent Skills spec) and workflows/.

Checks: name format (1-64 lowercase/digits/hyphens, no leading/trailing/double hyphen),
name == folder, description 1-1024 chars, compatibility <= 500 chars, SKILL.md < 500 lines,
every skill indexed exactly once, metadata.tier matches the index, every script referenced
in SKILL.md exists, workflows reference known skills, and every SKILL.md has a `## Never` section.
Exit code 1 on any error.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    end = text.index("\n---", 4)
    return yaml.safe_load(text[4:end]), text[end + 4:]


def main() -> int:
    errors: list[str] = []
    index = yaml.safe_load((ROOT / "skills-index.yaml").read_text())
    ids = [s["id"] for s in index["skills"]]
    if len(ids) != len(set(ids)):
        errors.append("duplicate ids in skills-index.yaml")
    dirs = sorted(p.name for p in (ROOT / "skills").iterdir() if p.is_dir())
    for missing in set(dirs) ^ set(ids):
        errors.append(f"skill {missing!r} is in only one of skills/ and skills-index.yaml")
    tiers = {s["id"]: s["tier"] for s in index["skills"]}
    for d in dirs:
        path = ROOT / "skills" / d / "SKILL.md"
        if not path.exists():
            errors.append(f"{d}: SKILL.md missing")
            continue
        text = path.read_text()
        try:
            fm, body = frontmatter(text)
        except ValueError as e:
            errors.append(f"{d}: {e}")
            continue
        name = fm.get("name", "")
        if not (1 <= len(name) <= 64 and NAME_RE.match(name)):
            errors.append(f"{d}: invalid name {name!r}")
        if name != d:
            errors.append(f"{d}: name {name!r} must equal folder name")
        desc = fm.get("description", "")
        if not (1 <= len(desc) <= 1024):
            errors.append(f"{d}: description length {len(desc)} not in 1..1024")
        if "use when" not in desc.lower():
            errors.append(f"{d}: description must say when to use the skill ('Use when ...')")
        if len(fm.get("compatibility", "")) > 500:
            errors.append(f"{d}: compatibility > 500 chars")
        meta = fm.get("metadata") or {}
        if not all(isinstance(v, str) for v in meta.values()):
            errors.append(f"{d}: metadata values must be strings")
        if d in tiers and meta.get("tier") != tiers[d]:
            errors.append(f"{d}: metadata.tier {meta.get('tier')!r} != index tier {tiers[d]!r}")
        if len(text.splitlines()) >= 500:
            errors.append(f"{d}: SKILL.md must be < 500 lines")
        if "## Never" not in body:
            errors.append(f"{d}: missing '## Never' section")
        for ref in set(re.findall(r"(scripts/[\w./-]+\.py|references/[\w./-]+\.md)", body)):
            if not (ROOT / "skills" / d / ref).exists():
                errors.append(f"{d}: referenced file {ref} does not exist")
    known = set(ids)
    for wf in index.get("workflows", []):
        f = ROOT / "workflows" / f"{wf['id']}.yaml"
        if not f.exists():
            errors.append(f"workflow file {f.name} missing")
            continue
        steps = yaml.safe_load(f.read_text())["steps"]
        used = [s["skill"] for s in steps]
        for s in used + wf["skills"]:
            if s not in known:
                errors.append(f"workflow {wf['id']}: unknown skill {s}")
    for e in errors:
        print("ERROR:", e)
    print(f"validated {len(dirs)} skills, {len(index.get('workflows', []))} workflows: "
          f"{'OK' if not errors else f'{len(errors)} error(s)'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
