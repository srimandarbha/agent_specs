"""Authoritative Agent State Schema for LangGraph.

Conforms to DEVELOPMENT_BLUEPRINT.md §4 and architecture/LANGGRAPH_DESIGN.md.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional, TypedDict
from pydantic import BaseModel, ConfigDict, Field
from .dossier import Dossier


class TrackType(str, Enum):
    TRACK_A = "track_a"  # Known deterministic skills (01-16)
    TRACK_B = "track_b"  # Exploratory unknown anomaly


class LifecycleStage(str, Enum):
    DRAIN = "drain"
    CONFIG_APPLY = "config_apply"
    PIVOT_REBOOT = "pivot_reboot"
    UNCORDON = "uncordon"
    MCP_ROLLOUT = "mcp_rollout"
    CLUSTER_UPGRADE = "cluster_upgrade"
    UNKNOWN = "unknown"


class PersistStatus(str, Enum):
    PENDING = "pending"
    PERSISTED = "persisted"
    FAILED = "failed"


class AgentState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Identifiers & Ingress Context
    investigation_id: str = Field(..., description="Unique investigation run ID")
    idempotency_key: str = Field(..., description="Deduplication key for ingress event")
    event_id: str = Field(..., description="Source event ID")
    trigger_type: str = Field("alert", description="alert or manual")

    # Normalized Cluster Context
    cluster_id: str = Field(..., description="Target OpenShift cluster ID")
    cluster_name: str = Field(..., description="Cluster human-readable name")
    openshift_version: str = Field(..., description="OpenShift release version")
    mco_version: Optional[str] = Field(None, description="MCO operator version")
    node_name: str = Field(..., description="Target node name")
    mcp_name: str = Field(..., description="MachineConfigPool name")

    # Lifecycle & Workflow Routing
    lifecycle_stage: LifecycleStage = Field(LifecycleStage.UNKNOWN, description="Classified lifecycle stage")
    use_case_id: Optional[str] = Field(None, description="Matched use case ID e.g. 01-pdb-eviction-blocked")
    skill_version: Optional[str] = Field(None, description="Loaded skill semver version")
    track: TrackType = Field(TrackType.TRACK_A, description="Selected execution track: track_a or track_b")

    # Runtime Budgets & Deadlines
    started_at: datetime = Field(..., description="Investigation start timestamp")
    deadline_at: datetime = Field(..., description="Hard 45s execution deadline")
    query_count_by_adapter: dict[str, int] = Field(
        default_factory=lambda: {"splunk_mcp": 0, "prometheus_mcp": 0},
        description="Adapter query call counts"
    )
    retry_count_by_adapter: dict[str, int] = Field(
        default_factory=lambda: {"splunk_mcp": 0, "prometheus_mcp": 0},
        description="Adapter retry counts"
    )

    # Evidence & Correlation State
    dossier: Optional[Dossier] = Field(None, description="Normalized evidence dossier")
    evidence_refs: list[str] = Field(default_factory=list, description="List of evidence IDs retained in context")
    evidence_quality: str = Field("valid", description="Aggregate evidence quality marker")
    missing_evidence: list[str] = Field(default_factory=list, description="Missing mandatory evidence keys")
    contradictions: list[str] = Field(default_factory=list, description="Detected telemetry contradictions")

    # Diagnostic Findings
    classification: Optional[str] = Field(None, description="supported, not_supported, inconclusive, probable")
    confidence: Optional[str] = Field(None, description="high, medium, low")
    sub_branch: Optional[str] = Field(None, description="Sub-branch identified in skill decision tree")
    hypotheses: list[dict[str, Any]] = Field(default_factory=list, description="Ranked causal hypotheses")
    supporting_evidence_ids: list[str] = Field(default_factory=list, description="Evidence IDs proving the hypothesis")
    contradicting_evidence_ids: list[str] = Field(default_factory=list, description="Evidence IDs conflicting with hypothesis")

    # Remediation
    recommendation_type: Optional[str] = Field(None, description="ANSIBLE_PLAYBOOK_PSEUDOCODE, MANUAL_CLI_RUNBOOK, NONE")
    playbook_id: Optional[str] = Field(None, description="Catalog playbook ID if matched")
    catalog_revision: Optional[str] = Field(None, description="Remediation catalog revision")
    recommendation_payload: Optional[dict[str, Any]] = Field(None, description="Full remediation output spec")
    extra_vars: Optional[dict[str, Any]] = Field(None, description="AAP launch extra vars if playbook matched")

    # Persistence & Termination
    persist_status: PersistStatus = Field(PersistStatus.PENDING, description="PostgreSQL persistence state")
    terminal_reason: Optional[str] = Field(None, description="Canonical reason code from contracts/REASON_CODES.md")
    error: Optional[str] = Field(None, description="Unrecoverable runtime error if failed")


class AgentStateDict(TypedDict, total=False):
    """TypedDict representation for LangGraph node signatures."""
    investigation_id: str
    idempotency_key: str
    event_id: str
    trigger_type: str
    cluster_id: str
    cluster_name: str
    openshift_version: str
    mco_version: Optional[str]
    node_name: str
    mcp_name: str
    lifecycle_stage: str
    use_case_id: Optional[str]
    skill_version: Optional[str]
    track: str
    started_at: datetime
    deadline_at: datetime
    query_count_by_adapter: dict[str, int]
    retry_count_by_adapter: dict[str, int]
    dossier: Optional[dict[str, Any]]
    evidence_refs: list[str]
    evidence_quality: str
    missing_evidence: list[str]
    contradictions: list[str]
    classification: Optional[str]
    confidence: Optional[str]
    sub_branch: Optional[str]
    hypotheses: list[dict[str, Any]]
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    recommendation_type: Optional[str]
    playbook_id: Optional[str]
    catalog_revision: Optional[str]
    recommendation_payload: Optional[dict[str, Any]]
    extra_vars: Optional[dict[str, Any]]
    persist_status: str
    terminal_reason: Optional[str]
    error: Optional[str]
