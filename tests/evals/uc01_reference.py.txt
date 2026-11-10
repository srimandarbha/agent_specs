"""Independent reference oracle for use case 01 (PDB blocks eviction).

Written separately from agent/skills/facts_uc01.py and the rules in the skill front matter, on purpose:
tests/test_uc01_skill.py requires the rules engine and this oracle to agree on every fixture.
Dossier text is treated as data only.
"""
from __future__ import annotations

PDB_FRESHNESS_LIMIT_S = 300          # docs/OBSERVABILITY_MATRIX.md, active-incident PDB/Pod snapshots
SUPPORTED_KINDS = ("Deployment", "StatefulSet")
FORBIDDEN_FRAGMENTS = ("--force", "--grace-period=0", "minavailable: 0", "minavailable=0",
                       "delete pdb", "patch pdb", "ignore all previous")


def _out(cls, conf, sub_branch=None, stop=None, kind="none", playbook=None, extra_vars=None, blockers=None):
    return {"classification": cls, "confidence": conf, "sub_branch": sub_branch, "stop_reason": stop,
            "remediation_kind": kind, "playbook_id": playbook, "extra_vars": extra_vars,
            "blockers": blockers or []}


def _blockers(r: dict) -> list[str]:
    w, cap = r.get("workload_details"), r.get("capacity_details")
    if w is None:
        return ["workload_unknown"]
    out = []
    if w.get("kind") not in SUPPORTED_KINDS:
        out.append("workload_kind_unsupported")
    for key, name in (("hpa_present", "hpa_present"), ("gitops_managed", "gitops_managed"),
                      ("has_volume_claim_templates", "volume_claim_templates"),
                      ("quota_blocks_scale_up", "quota_blocks_scale_up")):
        v = w.get(key)
        if v is True:
            out.append(name)
        elif v is None:
            out.append(name + "_unknown")
    if cap is None:
        out.append("capacity_unknown")
    elif not (cap["free_cpu_m"] > cap["pod_request_cpu_m"] and cap["free_mem_mi"] > cap["pod_request_mem_mi"]):
        out.append("capacity_insufficient")
    return out


def classify(dossier: dict, target: dict) -> dict:
    if dossier.get("status") == "error":
        return _out("inconclusive", "low", stop="telemetry_backend_unavailable")
    all_recs = dossier.get("records", [])
    recs = [x for x in all_recs if x.get("cluster_id") == target["cluster_id"]]
    if all_recs and not recs:
        return _out("inconclusive", "low", stop="wrong_cluster_evidence")
    if not all_recs:
        return _out("inconclusive", "low", stop="no_evidence")
    if not recs:
        return _out("inconclusive", "low", stop="wrong_cluster_evidence")
    r = recs[0]
    errs = [e.lower() for e in (r.get("controller_eviction_errors") or [])]
    denied = any("disruption budget" in e or "more than one poddisruptionbudget" in e
                 or ("429" in e and "too many requests" in e) for e in errs)
    multi = any("more than one poddisruptionbudget" in e for e in errs)
    pdb = r.get("pdb_details")

    if not denied:
        if pdb and pdb.get("disruptions_allowed", 0) > 0:
            return _out("not_supported", "high", stop="pdb_disruptions_allowed_positive")
        return _out("not_supported", "medium", stop="no_pdb_eviction_denial_logged")
    if pdb is None:
        return _out("probable", "medium", stop="pdb_record_missing_from_cache")
    if multi or pdb.get("overlapping_pdb_count", 1) > 1:
        return _out("inconclusive", "low", stop="multiple_overlapping_pdbs_detected")
    if pdb.get("overlapping_pdb_count", 1) == 0:
        return _out("probable", "medium", stop="pdb_deleted_or_selector_mismatch")
    if dossier.get("freshness") == "stale" or pdb.get("snapshot_age_s", 0) > PDB_FRESHNESS_LIMIT_S:
        return _out("inconclusive", "low", stop="pdb_state_stale")
    if pdb.get("disruptions_allowed", 0) > 0:
        return _out("inconclusive", "low", stop="contradictory_telemetry")

    wl = r.get("workload_details")
    sibs = r.get("sibling_pods") or []
    if wl and wl["desired_replicas"] == 1 and (pdb.get("min_available") == 1 or pdb.get("max_unavailable") in (0, "0%")):
        return _out("supported", "high", "3C_single_replica", kind="manual_cli")
    if any(s.get("waiting_reason") == "CrashLoopBackOff" or (not s["ready"] and s.get("restart_count", 0) >= 3)
           for s in sibs):
        return _out("supported", "high", "3A_crashing_sibling", kind="manual_cli")
    if any(s["phase"] == "Pending" and "Insufficient" in (s.get("scheduler_message") or "") for s in sibs):
        return _out("supported", "high", "3D_capacity_starvation", kind="manual_cli")
    if pdb["current_healthy"] < pdb["desired_healthy"]:
        return _out("supported", "medium", "3A_unready_sibling", kind="manual_cli")

    all_ready = bool(wl) and all(s["ready"] for s in sibs) and wl["ready_replicas"] == wl["desired_replicas"]
    if pdb["disruptions_allowed"] == 0 and pdb["current_healthy"] == pdb["desired_healthy"] and all_ready:
        blockers = _blockers(r)
        if blockers:
            return _out("supported", "medium", "3B_multi_replica_at_min_available", kind="manual_cli", blockers=blockers)
        n = wl["desired_replicas"]
        return _out("supported", "high", "3B_multi_replica_at_min_available", kind="playbook",
                    playbook="playbook_pdb_scale_up",
                    extra_vars={"target_cluster": r["cluster_id"], "target_namespace": r["target_namespace"],
                                "workload_kind": wl["kind"], "workload_name": wl["name"],
                                "target_pdb_name": pdb["name"], "current_replicas": n, "scale_to": n + 1})
    return _out("inconclusive", "low", stop="no_branch_matched")


def check_no_forbidden(text: str) -> list[str]:
    low = text.lower()
    return [f for f in FORBIDDEN_FRAGMENTS if f in low]
