"""Deterministic fact derivation for UC01. All matching and arithmetic lives here, in code.
Skill rules only compare the named facts below. Dossier text is data, never instructions."""
from __future__ import annotations
import re
from typing import Any
from .dossier import Uc01Dossier
from .loader import SkillMeta

SUPPORTED_KINDS = {"Deployment", "StatefulSet"}
FACT_NAMES = frozenset({
    "evidence.status", "evidence.record_count", "evidence.target_cluster_record_count",
    "denial.present", "denial.multi_pdb",
    "pdb.present", "pdb.selecting_count", "pdb.below_desired", "pdb.stale", "pdb.disruptions_allowed",
    "workload.single_replica_conflict", "siblings.crashing", "siblings.capacity_starved",
    "pdb.exhausted_all_ready", "scale_up.safe", "scale_up.blockers", "scale_up.extra_vars",
})


def _blockers(r) -> list[str]:
    w, cap, out = r.workload_details, r.capacity_details, []
    if w is None:
        return ["workload_unknown"]
    if w.kind not in SUPPORTED_KINDS:
        out.append("workload_kind_unsupported")
    for value, name in ((w.hpa_present, "hpa_present"), (w.gitops_managed, "gitops_managed"),
                        (w.has_volume_claim_templates, "volume_claim_templates"),
                        (w.quota_blocks_scale_up, "quota_blocks_scale_up")):
        if value is True: out.append(name)
        elif value is None: out.append(f"{name}_unknown")
    if cap is None:
        out.append("capacity_unknown")
    elif not (cap.free_cpu_m > cap.pod_request_cpu_m and cap.free_mem_mi > cap.pod_request_mem_mi):
        out.append("capacity_insufficient")
    return out


def derive(dossier: Uc01Dossier, target: dict[str, Any], meta: SkillMeta) -> dict[str, Any]:
    limit = meta.freshness_limits_seconds["pdb_pod_snapshot"]
    recs = [r for r in dossier.records if r.cluster_id == target["cluster_id"]]
    r = recs[0] if recs else None
    errs = r.controller_eviction_errors if r else []

    def sig_hit(text: str, signal: str | None = None) -> bool:
        return any(re.search(s.pattern, text) for s in meta.trigger_signatures
                   if signal is None or s.signal == signal)

    pdb = r.pdb_details if r else None
    w = r.workload_details if r else None
    sibs = r.sibling_pods if r else []
    all_ready = bool(w and all(s.ready for s in sibs) and w.ready_replicas == w.desired_replicas)
    blockers = _blockers(r) if r else ["no_record"]
    f: dict[str, Any] = {
        "evidence.status": dossier.status,
        "evidence.record_count": len(dossier.records),
        "evidence.target_cluster_record_count": len(recs),
        "denial.present": any(sig_hit(e) for e in errs),
        "denial.multi_pdb": any(sig_hit(e, "multi_pdb") for e in errs),
        "pdb.present": pdb is not None,
        "pdb.selecting_count": pdb.overlapping_pdb_count if pdb else 0,
        "pdb.below_desired": bool(pdb and pdb.current_healthy < pdb.desired_healthy),
        "pdb.stale": bool(pdb and (pdb.snapshot_age_s > limit or dossier.freshness == "stale")),
        "pdb.disruptions_allowed": pdb.disruptions_allowed if pdb else None,
        "workload.single_replica_conflict": bool(
            w and pdb and w.desired_replicas == 1 and (pdb.min_available == 1 or pdb.max_unavailable in (0, "0%"))),
        "siblings.crashing": any(s.waiting_reason == "CrashLoopBackOff" or (not s.ready and s.restart_count >= 3)
                                 for s in sibs),
        "siblings.capacity_starved": any(s.phase == "Pending" and "Insufficient" in (s.scheduler_message or "")
                                         for s in sibs),
        "pdb.exhausted_all_ready": bool(pdb and pdb.disruptions_allowed == 0
                                        and pdb.current_healthy == pdb.desired_healthy and all_ready),
        "scale_up.blockers": blockers,
        "scale_up.safe": not blockers,
        "scale_up.extra_vars": None,
    }
    if not blockers and w and pdb:
        f["scale_up.extra_vars"] = {
            "target_cluster": r.cluster_id, "target_namespace": r.target_namespace,
            "workload_kind": w.kind, "workload_name": w.name, "target_pdb_name": pdb.name,
            "current_replicas": w.desired_replicas, "scale_to": w.desired_replicas + 1}
    assert set(f) == FACT_NAMES, set(f) ^ FACT_NAMES
    return f
