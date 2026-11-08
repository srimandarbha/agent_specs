"""Reason-code registry: the Markdown is the source, the JSON is generated, and nothing unregistered is used."""
import json, pathlib, re, sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.skills.registry import build_registry, load_registry, parse_markdown, JSON_PATH

PATTERN = re.compile(r"(inconclusive|not_supported|probable|supported):\s*`?([a-z][a-z0-9_]+)")


def test_json_matches_markdown():
    assert JSON_PATH.exists(), "run tools/build_reason_registry.py"
    assert json.loads(JSON_PATH.read_text()) == build_registry()


def test_no_duplicate_codes_with_conflicting_status():
    rows = parse_markdown()
    by_code = {}
    for r in rows:
        by_code.setdefault(r["code"], set()).add(r["classification"])
    conflicts = {c: s for c, s in by_code.items() if len(s) > 1}
    assert not conflicts, conflicts


def test_registry_has_global_codes_used_by_uc01():
    reg = load_registry()
    for code in ("telemetry_backend_unavailable", "wrong_cluster_evidence", "no_evidence", "pdb_state_stale",
                 "multiple_overlapping_pdbs_detected", "contradictory_telemetry", "pdb_disruptions_allowed_positive"):
        assert code in reg, code


def test_uc01_skill_uses_only_registered_codes():
    text = (ROOT / "use-cases/01-pdb-eviction-blocked/skill.md").read_text()
    reg = load_registry()
    bad = [(cls, code) for cls, code in PATTERN.findall(text)
           if code not in reg or reg[code]["classification"] != cls]
    assert not bad, bad


def test_fixture_stop_reasons_registered():
    reg = load_registry()
    for f in (ROOT / "tests/fixtures").rglob("*_expected.json"):
        e = json.loads(f.read_text())
        code = e.get("stop_reason")
        if code:
            assert code in reg and reg[code]["classification"] == e["classification"], f.name


@pytest.mark.xfail(strict=True, reason="UC02-UC16 skills are not yet reviewed; codes like "
                   "overlapping_pdb_configuration are aliases, not registered codes. Remove this marker when fixed.")
def test_all_skill_codes_registered():
    reg = load_registry()
    bad = []
    for f in sorted((ROOT / "use-cases").glob("*/skill.md")):
        for cls, code in PATTERN.findall(f.read_text()):
            if code not in reg or reg[code]["classification"] != cls:
                bad.append(f"{f.parent.name}: {cls}:{code}")
    assert not bad, bad
