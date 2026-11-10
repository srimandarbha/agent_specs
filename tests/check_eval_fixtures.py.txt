#!/usr/bin/env python3
"""Verify every fixture path referenced by use-cases/*/eval.md exists."""
from __future__ import annotations
import re
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
FIXTURE_REF = re.compile(r"`(tests/fixtures/[^`]+)`")

def main() -> int:
    eval_files = sorted((REPO / "use-cases").glob("*/eval.md"))
    missing: list[tuple[Path, str]] = []
    refs = 0
    for eval_file in eval_files:
        content = eval_file.read_text(encoding="utf-8")
        for ref in sorted(set(FIXTURE_REF.findall(content))):
            refs += 1
            if not (REPO / ref).is_file():
                missing.append((eval_file.relative_to(REPO), ref))
    print(f"Use-case eval files: {len(eval_files)}")
    print(f"Unique fixture references checked: {refs}")
    print(f"Missing fixture references: {len(missing)}")
    for source, ref in missing:
        print(f"MISSING: {source} -> {ref}")
    if missing:
        print("Evaluation suite is incomplete; this is a visibility check, not a test pass.")
        return 1
    print("All referenced fixtures exist.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
