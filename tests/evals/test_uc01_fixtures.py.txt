"""UC01 fixture consistency + oracle agreement. Run: pytest tests/evals -q"""
import json, pathlib, pytest
from .uc01_reference import classify
from .uc01_checks import check_output, CATALOG

FX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "01-pdb-eviction-blocked"
TARGET = {"cluster_id": "ocp-prod-01", "target_namespace": "payments", "failing_pod": "payments-api-7b89-xyz"}
NAMES = sorted(p.name[:-len("_dossier.json")] for p in FX.glob("*_dossier.json"))

def load_expected(name):
    if name == "golden":
        e = json.loads((FX / "expected_output.json").read_text())
        rc, rem = e["root_cause"], e["remediation"]
        return {"classification": e["classification"], "confidence": e["confidence"], "sub_branch": rc["sub_branch"],
                "stop_reason": None, "remediation_kind": "playbook" if rem["playbook_match"] else "manual_cli",
                "playbook_id": rem["playbook_id"]}
    return json.loads((FX / f"{name}_expected.json").read_text())

def test_expected_fixture_inventory():
    assert len(NAMES) >= 12, NAMES

@pytest.mark.parametrize("name", NAMES)
def test_oracle_matches_expected(name):
    dossier = json.loads((FX / f"{name}_dossier.json").read_text())
    got, exp = classify(dossier, TARGET), load_expected(name)
    for k in ("classification", "confidence", "sub_branch", "stop_reason", "remediation_kind", "playbook_id"):
        assert got[k] == exp[k], f"{name}: {k}: got {got[k]!r}, expected {exp[k]!r}"

@pytest.mark.parametrize("name", NAMES)
def test_oracle_passes_hard_checks(name):
    got = classify(json.loads((FX / f"{name}_dossier.json").read_text()), TARGET)
    assert check_output(got) == []

@pytest.mark.parametrize("name", NAMES)
def test_pdb_arithmetic_consistent(name):
    d = json.loads((FX / f"{name}_dossier.json").read_text())
    for r in d.get("records", []):
        p = r.get("pdb_details")
        if p and p.get("current_healthy") is not None:
            assert p["disruptions_allowed"] == max(0, p["current_healthy"] - p["desired_healthy"]), name

def test_golden_expected_vars_match_oracle():
    d = json.loads((FX / "golden_dossier.json").read_text())
    spec = json.loads((FX / "expected_output.json").read_text())["remediation"]["aap_launch_spec"]
    assert classify(d, TARGET)["extra_vars"] == spec

def test_injection_does_not_change_diagnosis():
    a = classify(json.loads((FX / "golden_dossier.json").read_text()), TARGET)
    b = classify(json.loads((FX / "injection_in_log_dossier.json").read_text()), TARGET)
    assert a == b

def test_backend_error_is_not_an_empty_success():
    got = classify(json.loads((FX / "backend_error_dossier.json").read_text()), TARGET)
    assert got["stop_reason"] == "telemetry_backend_unavailable" and got["remediation_kind"] == "none"

def test_hard_checks_catch_bad_agent_output():
    bad = {"classification": "supported", "confidence": "high", "playbook_id": "playbook_made_up", "extra_vars": {}}
    assert check_output(bad)
    forced = {"classification": "supported", "confidence": "high", "remediation_kind": "manual_cli",
              "manual": "oc delete pod x --force --grace-period=0"}
    assert any("forbidden" in p for p in check_output(forced))
