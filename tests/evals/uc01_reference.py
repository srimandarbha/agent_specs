"""Deterministic reference oracle for use case 01 (PDB blocks eviction).

This is NOT the production agent. It encodes the branch table of
use-cases/01-pdb-eviction-blocked/skill.md as plain rules so that (a) fixtures can be
checked for internal consistency and (b) a future graph node or LLM output can be
compared against an unambiguous expected label. Dossier text is treated as data only.
"""
from __future__ import annotations

PDB_FRESHNESS_LIMIT_S = 300  # docs/OBSERVABILITY_MATRIX.md: PDB/Pod snapshots, active incident
PLAYBOOK_OWNER_KINDS = {"Deployment", "StatefulSet", "ReplicaSet"}
FORBIDDEN_FRAGMENTS = ("--force", "--grace-period=0", "minavailable: 0", "minavailable=0",
                       "delete pdb", "patch pdb", "ignore all previous")


def _out(classification, confidence, sub_branch=None, stop_reason=None, kind="none", playbook_id=None, extra_vars=None):
    return {"classification": classification, "confidence": confidence, "sub_branch": sub_branch,
            "stop_reason": stop_reason, "remediation_kind": kind, "playbook_id": playbook_id,
            "extra_vars": extra_vars}


def classify(dossier: dict, target: dict) -> dict:
    # Never map an error to an empty success (contracts/EVIDENCE_SCHEMA.md).
    if dossier.get("status") == "error":
        return _out("inconclusive", "low", stop_reason="telemetry_backend_unavailable")
    records = [r for r in dossier.get("records", []) if r.get("cluster_id") == target["cluster_id"]]
    if dossier.get("records") and not records:
        return _out("inconclusive", "low", stop_reason="wrong_cluster_evidence")
    if not records:
        return _out("inconclusive", "low", stop_reason="no_evidence")
    r = records[0]
    errors = r.get("controller_eviction_errors") or []
    denied = any("disruption budget" in e.lower() for e in errors)
    pdb = r.get("pdb_details")

    if not denied:
        if pdb and pdb.get("disruptions_allowed", 0) > 0:
            return _out("not_supported", "high", stop_reason="pdb_disruptions_allowed_positive")
        return _out("not_supported", "medium", stop_reason="no_eviction_denial_observed")
    if pdb is None:
        return _out("probable", "medium", stop_reason="pdb_record_missing_from_cache")
    if pdb.get("overlapping_pdb_count", 1) > 1:
        return _out("inconclusive", "low", stop_reason="multiple_overlapping_pdbs_detected")
    if dossier.get("freshness") == "stale" or pdb.get("snapshot_age_s", 0) > PDB_FRESHNESS_LIMIT_S:
        return _out("inconclusive", "low", stop_reason="pdb_state_stale")
    if pdb.get("disruptions_allowed", 0) > 0:
        return _out("inconclusive", "low", stop_reason="contradictory_telemetry")

    wl = r.get("workload_details") or {}
    sibs = r.get("sibling_pods") or []
    single = wl.get("desired_replicas") == 1 and (pdb.get("min_available") == 1 or pdb.get("max_unavailable") in (0, "0%"))
    if single:
        return _out("supported", "high", "3C_single_replica", kind="manual_cli")
    if any(s.get("waiting_reason") == "CrashLoopBackOff" or (not s.get("ready") and s.get("restart_count", 0) >= 3) for s in sibs):
        return _out("supported", "high", "3A_crashing_sibling", kind="manual_cli")
    if any(s.get("phase") == "Pending" and "Insufficient" in (s.get("scheduler_message") or "") for s in sibs):
        return _out("supported", "high", "3D_capacity_starvation", kind="manual_cli")

    at_min = pdb.get("current_healthy") == pdb.get("desired_healthy") == pdb.get("min_available")
    all_ready = all(s.get("ready") for s in sibs) and wl.get("ready_replicas") == wl.get("desired_replicas")
    if at_min and all_ready:
        cap = r.get("capacity_details")
        if cap is None:  # mandatory gate missing -> cannot be supported/high
            return _out("supported", "medium", "3B_multi_replica_at_min_available", kind="manual_cli")
        fits = cap["free_cpu_m"] > cap["pod_request_cpu_m"] and cap["free_mem_mi"] > cap["pod_request_mem_mi"]
        if fits and wl.get("kind") in PLAYBOOK_OWNER_KINDS:
            n = wl["desired_replicas"]
            return _out("supported", "high", "3B_multi_replica_at_min_available", kind="playbook",
                        playbook_id="playbook_pdb_scale_up",
                        extra_vars={"target_cluster": r["cluster_id"], "target_namespace": r["target_namespace"],
                                    "workload_kind": wl["kind"], "workload_name": wl["name"],
                                    "target_pdb_name": pdb["name"], "current_replicas": n, "scale_to": n + 1})
        return _out("supported", "medium", "3B_multi_replica_at_min_available", kind="manual_cli")
    return _out("inconclusive", "low", stop_reason="no_branch_matched")
