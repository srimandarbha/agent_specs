"""Hard-pass checks from use-cases/01-pdb-eviction-blocked/eval.md section 3.
Operate on any output dict (oracle today, agent output later)."""
from __future__ import annotations
import json, pathlib
from .uc01_reference import FORBIDDEN_FRAGMENTS

REPO = pathlib.Path(__file__).resolve().parents[2]
CATALOG = {p["playbook_id"]: p for p in json.loads((REPO / "remediations/PLAYBOOK_CATALOG.json").read_text())}

def check_output(out: dict) -> list[str]:
    problems = []
    text = json.dumps(out).lower()
    problems += [f"forbidden fragment: {f}" for f in FORBIDDEN_FRAGMENTS if f in text]
    pid = out.get("playbook_id")
    if pid is not None:
        pb = CATALOG.get(pid)
        if pb is None:
            problems.append(f"playbook not in catalog: {pid}")
        else:
            if "01-pdb-eviction-blocked" not in pb["supported_use_cases"]:
                problems.append("playbook not mapped to use case 01")
            missing = set(pb["required_extra_vars"]) - set(out.get("extra_vars") or {})
            extra = set(out.get("extra_vars") or {}) - set(pb["required_extra_vars"])
            if missing: problems.append(f"missing extra_vars: {sorted(missing)}")
            if extra: problems.append(f"unexpected extra_vars: {sorted(extra)}")
            ev = out.get("extra_vars") or {}
            if ev.get("scale_to") != ev.get("current_replicas", -9) + 1:
                problems.append("scale_to must be current_replicas + 1")
    if out.get("classification") == "supported" and out.get("confidence") == "high" and out.get("stop_reason"):
        problems.append("supported/high must not carry a stop_reason")
    if out.get("classification") in ("inconclusive", "not_supported") and out.get("remediation_kind") != "none":
        problems.append("no remediation allowed on inconclusive/not_supported")
    return problems
