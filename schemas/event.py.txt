"""Authoritative Event Envelope and Ingress Contract Schemas.

Conforms to contracts/EVENT_CONTRACT.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TriggerType(str, Enum):
    ALERT = "alert"
    MANUAL = "manual"


class AlertDetails(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Alert rule name e.g. MachineConfigControllerDrainError")
    fingerprint: Optional[str] = Field(None, description="Stable alert fingerprint from Alertmanager")
    severity: str = Field("warning", description="Alert severity level (warning, critical, info)")
    labels: dict[str, str] = Field(default_factory=dict, description="Raw alert labels from Alertmanager")
    annotations: dict[str, str] = Field(default_factory=dict, description="Alert annotations / descriptions")


class RequestDetails(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: Optional[str] = Field(None, description="User or ticket investigation brief (untrusted text)")
    requested_by: Optional[str] = Field(None, description="Authenticated principal requesting investigation")
    change_id: Optional[str] = Field(None, description="Associated change request / CRQ ID")


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field("1.0", description="Contract schema version")
    event_id: str = Field(..., description="Unique event identifier")
    event_type: str = Field(..., description="Reverse-DNS event type e.g. com.example.openshift.mco.drain.alert")
    occurred_at: datetime = Field(..., description="Timestamp when the event occurred at source")
    received_at: datetime = Field(..., description="Timestamp when the event entered the pipeline")
    trigger_type: TriggerType = Field(..., description="Ingress trigger mode: alert or manual")
    source: str = Field(..., description="Ingress source e.g. alertmanager, web-console, cli")
    cluster_id: str = Field(..., min_length=1, description="Explicit target cluster ID")
    cluster_name: str = Field(..., min_length=1, description="Cluster human-readable name")
    openshift_version: str = Field(..., description="OpenShift release version e.g. 4.22.z")
    node_name: str = Field(..., min_length=1, description="Target node undergoing drain / maintenance")
    mcp_name: str = Field(..., min_length=1, description="Target MachineConfigPool name (e.g. worker, master)")
    alert: Optional[AlertDetails] = Field(None, description="Alert payload when trigger_type=alert")
    request: Optional[RequestDetails] = Field(None, description="User request payload when trigger_type=manual")
    trace_id: Optional[str] = Field(None, description="Distributed trace ID for observability correlation")

    @model_validator(mode="after")
    def validate_trigger_consistency(self) -> EventEnvelope:
        if self.schema_version != "1.0":
            raise ValueError(f"Unsupported schema_version: {self.schema_version}. Expected '1.0'")
        
        if self.trigger_type == TriggerType.ALERT:
            if not self.alert or not self.alert.name:
                raise ValueError("trigger_type='alert' requires an 'alert' payload with a valid 'name'")
        elif self.trigger_type == TriggerType.MANUAL:
            if not self.request or not self.request.requested_by:
                raise ValueError("trigger_type='manual' requires an authenticated principal in 'request.requested_by'")
        return self

    def generate_idempotency_key(self, bucket_minutes: int = 15) -> str:
        """Computes a stable idempotency key bucketed by time.
        
        Preferred formula from contracts/EVENT_CONTRACT.md:
        fingerprint/event_id + cluster_id + alert_name/manual + node_name + time_bucket
        """
        # Truncate occurred_at to time bucket
        ts = int(self.occurred_at.timestamp())
        bucket_seconds = bucket_minutes * 60
        bucket_id = ts // bucket_seconds

        sig_source = self.alert.fingerprint if (self.alert and self.alert.fingerprint) else self.event_id
        signal_name = self.alert.name if self.alert else "manual_investigation"

        raw = f"{sig_source}:{self.cluster_id}:{signal_name}:{self.node_name}:{bucket_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
