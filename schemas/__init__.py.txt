"""Canonical Pydantic Schemas for Multi-Cluster MCO Diagnostic Agent.

Provides strongly-typed, schema-validated contracts for:
- Event Ingress (EventEnvelope, TriggerType, AlertDetails, RequestDetails)
- Evidence Records (EvidenceRecord, ResourceIdentifier, MetricPayload, EvidenceType)
- Dossiers & Relationships (Dossier, RelationshipRecord, AdapterQueryResult)
- Agent State (AgentState, AgentStateDict, TrackType, LifecycleStage)
- Reports & Remediations (InvestigationReport, RemediationReport, RootCause, OracleOutput)
"""
from __future__ import annotations

from .event import (
    AlertDetails,
    EventEnvelope,
    RequestDetails,
    TriggerType,
)
from .evidence import (
    EvidenceRecord,
    EvidenceType,
    Freshness,
    MetricPayload,
    Quality,
    RedactionStatus,
    ResourceIdentifier,
)
from .dossier import (
    AdapterQueryResult,
    CollectionWindow,
    Dossier,
    DossierStatus,
    RelationshipRecord,
    RelationshipResult,
)
from .state import (
    AgentState,
    AgentStateDict,
    LifecycleStage,
    PersistStatus,
    TrackType,
)
from .report import (
    Classification,
    Confidence,
    EvidenceCitation,
    Hypothesis,
    InvestigationReport,
    ManualCLIFallback,
    OracleOutput,
    RemediationKind,
    RemediationReport,
    RemediationType,
    RootCause,
    TargetContext,
)

__all__ = [
    # Event
    "AlertDetails",
    "EventEnvelope",
    "RequestDetails",
    "TriggerType",
    # Evidence
    "EvidenceRecord",
    "EvidenceType",
    "Freshness",
    "MetricPayload",
    "Quality",
    "RedactionStatus",
    "ResourceIdentifier",
    # Dossier
    "AdapterQueryResult",
    "CollectionWindow",
    "Dossier",
    "DossierStatus",
    "RelationshipRecord",
    "RelationshipResult",
    # State
    "AgentState",
    "AgentStateDict",
    "LifecycleStage",
    "PersistStatus",
    "TrackType",
    # Report
    "Classification",
    "Confidence",
    "EvidenceCitation",
    "Hypothesis",
    "InvestigationReport",
    "ManualCLIFallback",
    "OracleOutput",
    "RemediationKind",
    "RemediationReport",
    "RemediationType",
    "RootCause",
    "TargetContext",
]
