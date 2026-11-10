#!/usr/bin/env python3
"""Regenerate contracts/reason_codes.json from contracts/REASON_CODES.md.
  python3 tools/build_reason_registry.py          # write
  python3 tools/build_reason_registry.py --check  # exit 1 if the JSON is stale"""
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from agent.skills.registry import build_registry, JSON_PATH

if __name__ == "__main__":
    text = json.dumps(build_registry(), indent=2) + "\n"
    if "--check" in sys.argv:
        ok = JSON_PATH.exists() and JSON_PATH.read_text() == text
        print("registry up to date" if ok else "registry STALE: run tools/build_reason_registry.py")
        sys.exit(0 if ok else 1)
    JSON_PATH.write_text(text)
    print("wrote", len(json.loads(text)["codes"]), "codes to", JSON_PATH)
