"""Authoritative Evidence Record Schema.

Conforms to contracts/EVIDENCE_SCHEMA.md.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class EvidenceType(str, Enum):
    LOG = "log"
    OBJECT_SNAPSHOT = "object_snapshot"
    OBJECT_CHANGE = "object_change"
    EVENT = "event"
    METRIC = "metric"
    AUDIT = "audit"


class Freshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class Quality(str, Enum):
    VALID = "valid"
    PARTIAL = "partial"
    MALFORMED = "malformed"
    CONTRADICTORY = "contradictory"


class RedactionStatus(str, Enum):
    REDACTED = "redacted"
    UNREDACTED = "unredacted"
    NONE_NEEDED = "none_needed"


class ResourceIdentifier(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_version: str = Field(..., description="Kubernetes apiVersion e.g. policy/v1, v1")
    kind: str = Field(..., description="Kubernetes Kind e.g. PodDisruptionBudget, Pod, Node")
    namespace: Optional[str] = Field(None, description="Namespace if resource is namespaced")
    name: str = Field(..., description="Resource name")
    uid: Optional[str] = Field(None, description="Kubernetes object UID")
    resource_version: Optional[str] = Field(None, description="Resource version for ordering snapshots")


class MetricPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    metric_name: str = Field(..., description="Prometheus metric name")
    labels: dict[str, str] = Field(default_factory=dict, description="Metric label dimensions")
    value: float = Field(..., description="Evaluated metric float value")
    unit: Optional[str] = Field(None, description="Metric unit e.g. bytes, ratio, seconds")
    sample_timestamp: datetime = Field(..., description="Timestamp of the Prometheus sample")
    aggregation_window: Optional[str] = Field(None, description="Aggregation window e.g. 5m, 1h")
    query_resolution: Optional[str] = Field(None, description="PromQL step resolution e.g. 15s")


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    evidence_id: str = Field(..., description="Unique evidence ID (ev-*)")
    source_adapter: str = Field(..., description="Adapter name: splunk_mcp or prometheus_mcp")
    source_dataset: str = Field(..., description="Dataset name e.g. ocp_logs, k8s_objects, ocp_metrics")
    source_query_id: str = Field(..., description="Traceable query execution ID")
    cluster_id: str = Field(..., description="Cluster from which telemetry was extracted")
    resource: Optional[ResourceIdentifier] = Field(None, description="Kubernetes resource target")
    evidence_type: EvidenceType = Field(..., description="Type of evidence record")
    event_time: datetime = Field(..., description="When the raw event occurred in the cluster")
    observed_at: datetime = Field(..., description="When telemetry was observed by monitoring")
    ingested_at: datetime = Field(..., description="When record was ingested into telemetry backend")
    retrieved_at: datetime = Field(..., description="When adapter executed the query and fetched it")
    freshness: Freshness = Field(Freshness.FRESH, description="Freshness evaluation against matrix limits")
    quality: Quality = Field(Quality.VALID, description="Quality classification of evidence")
    fields: dict[str, Any] = Field(default_factory=dict, description="Normalized key-value attributes")
    excerpt: Optional[str] = Field(None, max_length=2000, description="Bounded redacted excerpt of log/object")
    content_hash: Optional[str] = Field(None, description="SHA256 hash of raw extracted payload")
    redaction_status: RedactionStatus = Field(RedactionStatus.REDACTED, description="Redaction gate status")
    collector_version: Optional[str] = Field(None, description="Telemetry collector version")
    source_revision: Optional[str] = Field(None, description="Telemetry source revision")
    metric: Optional[MetricPayload] = Field(None, description="Typed metric details when evidence_type=metric")
