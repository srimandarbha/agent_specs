"""Constrained rule interpreter for skill profile v1 (see contracts/SKILL_RULES.md section 6).
No eval, no templates, no I/O. Rules compare named facts only. First matching rule wins."""
from __future__ import annotations
import re
from typing import Any
from .loader import SkillMeta

OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "is_true", "is_false", "is_null", "not_null"}
TERMINAL_KEYS = {"classification", "confidence", "sub_branch", "reason_code", "remediation"}
REMEDIATION_KEYS = {"kind", "playbook_id", "extra_vars_fact", "blockers_fact"}


def _cmp(actual: Any, op: str, expected: Any = None) -> bool:
    if op == "eq": return actual == expected
    if op == "ne": return actual != expected
    if op in ("gt", "gte", "lt", "lte"):
        if actual is None or expected is None: return False   # unknown never satisfies a numeric test
        return {"gt": actual > expected, "gte": actual >= expected,
                "lt": actual < expected, "lte": actual <= expected}[op]
    if op == "in": return actual in (expected or [])
    if op == "is_true": return actual is True
    if op == "is_false": return actual is False
    if op == "is_null": return actual is None
    if op == "not_null": return actual is not None
    raise ValueError(f"unknown op {op}")


def matches(when: dict, facts: dict[str, Any]) -> bool:
    if "always" in when:
        return True
    if "all" in when:
        return all(_cmp(facts[c[0]], c[1], c[2] if len(c) > 2 else None) for c in when["all"])
    return any(_cmp(facts[c[0]], c[1], c[2] if len(c) > 2 else None) for c in when["any"])


def evaluate(meta: SkillMeta, facts: dict[str, Any]) -> dict[str, Any]:
    for rule in meta.rules:
        if matches(rule.when, facts):
            t = rule.then
            rem = t.get("remediation") or {}
            return {
                "rule_id": rule.id,
                "classification": t["classification"],
                "confidence": t["confidence"],
                "sub_branch": t.get("sub_branch"),
                "stop_reason": t.get("reason_code"),
                "remediation_kind": rem.get("kind", "none"),
                "playbook_id": rem.get("playbook_id"),
                "extra_vars": facts[rem["extra_vars_fact"]] if rem.get("extra_vars_fact") else None,
                "blockers": list(facts[rem["blockers_fact"]]) if rem.get("blockers_fact") else [],
            }
    raise RuntimeError("no rule matched; the last rule of every skill must be an always-rule")


def validate_skill(meta: SkillMeta, *, known_facts: set[str], registry: dict[str, dict],
                   catalog: dict[str, dict], repo) -> list[str]:
    """Static checks. Returns a list of problems (empty means valid)."""
    p: list[str] = []
    ids = [r.id for r in meta.rules]
    if len(ids) != len(set(ids)): p.append("duplicate rule ids")
    if not meta.rules or "always" not in meta.rules[-1].when: p.append("last rule must be an always-rule")
    if set(meta.declared_facts) != known_facts:
        p.append(f"declared_facts differ from code: {sorted(set(meta.declared_facts) ^ known_facts)}")
    if "pdb_pod_snapshot" not in meta.freshness_limits_seconds: p.append("freshness_limits_seconds.pdb_pod_snapshot missing")
    for s in meta.trigger_signatures:
        try: re.compile(s.pattern)
        except re.error as e: p.append(f"trigger pattern does not compile: {e}")
    for name, rel in meta.evaluation_fixtures.items():
        if not (repo / rel).exists(): p.append(f"evaluation fixture missing: {rel}")
    for r in meta.rules:
        for key in ("all", "any"):
            for c in r.when.get(key, []):
                if c[0] not in known_facts: p.append(f"{r.id}: unknown fact {c[0]}")
                if c[1] not in OPS: p.append(f"{r.id}: unknown op {c[1]}")
        if set(r.then) - TERMINAL_KEYS: p.append(f"{r.id}: unknown keys {sorted(set(r.then) - TERMINAL_KEYS)}")
        rem = r.then.get("remediation") or {}
        if set(rem) - REMEDIATION_KEYS: p.append(f"{r.id}: unknown remediation keys")
        cls, conf = r.then.get("classification"), r.then.get("confidence")
        code = r.then.get("reason_code")
        if cls == "supported":
            if code is not None: p.append(f"{r.id}: supported rules must not carry reason_code")
            if conf == "high" and rem.get("kind") != "playbook" and rem.get("kind") != "manual_cli":
                p.append(f"{r.id}: supported/high needs a remediation kind")
        else:
            if code is None: p.append(f"{r.id}: {cls} requires reason_code")
            elif code not in registry: p.append(f"{r.id}: unregistered reason_code {code}")
            elif registry[code]["classification"] != cls:
                p.append(f"{r.id}: {code} registered as {registry[code]['classification']}, used as {cls}")
            if rem.get("kind", "none") != "none": p.append(f"{r.id}: remediation not allowed on {cls}")
        if rem.get("kind") == "playbook":
            pid = rem.get("playbook_id")
            if pid not in catalog: p.append(f"{r.id}: playbook not in catalog: {pid}")
            if pid not in meta.remediation_catalog_refs: p.append(f"{r.id}: playbook not listed in remediation_catalog_refs")
            if rem.get("extra_vars_fact") not in known_facts: p.append(f"{r.id}: extra_vars_fact missing")
        if rem.get("blockers_fact") and rem["blockers_fact"] not in known_facts: p.append(f"{r.id}: blockers_fact missing")
    return p
