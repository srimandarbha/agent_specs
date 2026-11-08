"""Normalized dossier consumed by the UC01 diagnosis node (shape of tests/fixtures/01-pdb-eviction-blocked)."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class PodDetails(_Strict):
    name: str; namespace: str; owner_kind: str | None = None; owner_name: str | None = None
    labels: dict[str, str] = Field(default_factory=dict); phase: str

class PdbDetails(_Strict):
    name: str; namespace: str
    selector: dict | None = None
    min_available: int | str | None = None
    max_unavailable: int | str | None = None
    current_healthy: int; desired_healthy: int; disruptions_allowed: int
    expected_pods: int | None = None
    snapshot_age_s: int                      # seconds since the PDB snapshot was observed
    overlapping_pdb_count: int = 1           # number of PDBs selecting the failing pod

class WorkloadDetails(_Strict):
    kind: str; name: str; desired_replicas: int; ready_replicas: int
    # None = unknown. Unknown is NOT treated as "safe" by any rule.
    hpa_present: bool | None = None
    gitops_managed: bool | None = None
    has_volume_claim_templates: bool | None = None
    quota_blocks_scale_up: bool | None = None

class SiblingPod(_Strict):
    name: str; phase: str; ready: bool; restart_count: int = 0
    waiting_reason: str | None = None; scheduler_message: str | None = None

class CapacityDetails(_Strict):
    schedulable_nodes: int; free_cpu_m: int; free_mem_mi: int
    pod_request_cpu_m: int; pod_request_mem_mi: int

class NodeDetails(_Strict):
    name: str; conditions: dict[str, str] = Field(default_factory=dict)
    desired_drain: str | None = None; last_applied_drain: str | None = None

class Uc01Record(_Strict):
    cluster_id: str; target_namespace: str; target_resource: str; node_name: str
    first_seen: str; last_seen: str
    controller_eviction_errors: list[str] = Field(default_factory=list)   # UNTRUSTED text
    objects_observed: list[str] = Field(default_factory=list)
    pod_details: PodDetails | None = None
    pdb_details: PdbDetails | None = None
    workload_details: WorkloadDetails | None = None
    sibling_pods: list[SiblingPod] = Field(default_factory=list)
    capacity_details: CapacityDetails | None = None
    node_details: NodeDetails | None = None
    relevant_metrics: list[str] = Field(default_factory=list)

class AdapterErr(_Strict):
    adapter: str; error: str; retried: bool = False

class Uc01Dossier(_Strict):
    status: Literal["ok", "partial", "error"]
    freshness: Literal["fresh", "stale", "unknown"] = "unknown"
    quality: Literal["valid", "partial", "malformed", "contradictory"] = "valid"
    observed_at: str
    execution_time_ms: int = 0
    adapter_errors: list[AdapterErr] = Field(default_factory=list)
    records: list[Uc01Record] = Field(default_factory=list)
