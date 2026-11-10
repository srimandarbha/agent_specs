"""Authoritative Dossier and Correlation Schemas.

Conforms to contracts/EVIDENCE_SCHEMA.md and contracts/CORRELATION_ENGINE.md.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field
from .evidence import EvidenceRecord


class DossierStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    ERROR = "error"


class RelationshipResult(str, Enum):
    CONFIRMED = "confirmed"
    CANDIDATE = "candidate"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"


class RelationshipRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    relationship_id: str = Field(..., description="Unique relationship identifier (rel-*)")
    type: str = Field(..., description="Semantic link type e.g. pod_covered_by_pdb, pod_bound_to_pvc")
    from_evidence_id: str = Field(..., description="Source evidence ID")
    to_evidence_id: str = Field(..., description="Target evidence ID")
    join_rule: str = Field(..., description="Deterministic join rule identifier")
    result: RelationshipResult = Field(..., description="Evaluation outcome of the relationship")
    reason: str = Field(..., description="Explanation of match or mismatch rationale")


class AdapterQueryResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    adapter_name: str = Field(..., description="Name of the adapter (splunk_mcp, prometheus_mcp)")
    status: DossierStatus = Field(..., description="Query execution status: ok, partial, error")
    execution_time_ms: int = Field(0, description="Latency of the query call")
    records_count: int = Field(0, description="Number of telemetry records returned")
    error_code: Optional[str] = Field(None, description="Standardized error code if failed")
    error_message: Optional[str] = Field(None, description="Redacted error description if failed")


class CollectionWindow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    earliest: datetime = Field(..., description="Query window earliest boundary")
    latest: datetime = Field(..., description="Query window latest boundary")


class Dossier(BaseModel):
    model_config = ConfigDict(extra="ignore")

    investigation_id: Optional[str] = Field(None, description="Correlated investigation ID")
    cluster_id: Optional[str] = Field(None, description="Target cluster ID")
    node_name: Optional[str] = Field(None, description="Target node name")
    status: DossierStatus = Field(DossierStatus.OK, description="Dossier aggregate status: ok, partial, error")
    observed_at: datetime = Field(..., description="Timestamp of dossier observation/collection")
    execution_time_ms: int = Field(0, description="Total elapsed evidence gathering time")
    collection_window: Optional[CollectionWindow] = Field(None, description="Time range queried")
    adapter_results: list[AdapterQueryResult] = Field(default_factory=list, description="Per-adapter call details")
    records: list[dict[str, Any]] = Field(default_factory=list, description="Correlated incident records")
    evidence_items: list[EvidenceRecord] = Field(default_factory=list, description="Normalized canonical evidence items")
    relationships: list[RelationshipRecord] = Field(default_factory=list, description="Deterministic entity relationships")
    missing_evidence: list[str] = Field(default_factory=list, description="Declared evidence requirements that were absent")
    contradictions: list[str] = Field(default_factory=list, description="Contradictory evidence signals detected")
    freshness: Optional[str] = Field(None, description="Aggregate freshness marker (fresh, stale, partial)")
