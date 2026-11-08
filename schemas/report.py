"""Authoritative Investigation Report and Remediation Output Schemas.

Conforms to contracts/TOOL_CONTRACTS.md §4, contracts/EVIDENCE_SCHEMA.md §4,
and eval fixtures.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Classification(str, Enum):
    SUPPORTED = "supported"
    NOT_SUPPORTED = "not_supported"
    INCONCLUSIVE = "inconclusive"
    PROBABLE = "probable"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RemediationType(str, Enum):
    ANSIBLE_PLAYBOOK = "ANSIBLE_PLAYBOOK"
    ANSIBLE_PLAYBOOK_PSEUDOCODE = "ANSIBLE_PLAYBOOK_PSEUDOCODE"
    MANUAL_CLI_RUNBOOK = "MANUAL_CLI_RUNBOOK"
    NONE = "none"


class RemediationKind(str, Enum):
    PLAYBOOK = "playbook"
    MANUAL_CLI = "manual_cli"
    NONE = "none"


class TargetContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cluster_id: str = Field(..., description="Target cluster ID")
    target_namespace: Optional[str] = Field(None, description="Namespace of affected workload")
    failing_pod: Optional[str] = Field(None, description="Name of pod stalling eviction")
    target_node: Optional[str] = Field(None, description="Node being drained")
    target_pdb: Optional[str] = Field(None, description="PodDisruptionBudget name if applicable")


class EvidenceCitation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str = Field(..., description="Source dataset e.g. ocp_logs, k8s_objects, ocp_metrics")
    excerpt: Optional[str] = Field(None, description="Log line or description excerpt")
    resource: Optional[str] = Field(None, description="Kind/name of resource e.g. PodDisruptionBudget/payments-api-pdb")
    field: Optional[str] = Field(None, description="Field path e.g. status.disruptionsAllowed")
    value: Optional[Any] = Field(None, description="Observed value of the field")


class RootCause(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = Field(..., description="Clear explanatory synthesis of the root cause")
    sub_branch: Optional[str] = Field(None, description="Decision tree branch e.g. 3B_multi_replica_at_min_available")
    evidence_citations: list[EvidenceCitation] = Field(default_factory=list, description="Citations to verified evidence")


class ManualCLIFallback(BaseModel):
    model_config = ConfigDict(extra="ignore")

    command: Optional[str] = Field(None, description="Recommended safe manual inspection or scale command")
    verification: Optional[str] = Field(None, description="Command to verify recovery")
    risk_level: Optional[str] = Field(None, description="Risk assessment: low, medium, high")
    pre_checks: list[str] = Field(default_factory=list, description="Pre-execution sanity check commands")
    remediation_steps: list[str] = Field(default_factory=list, description="Step-by-step CLI commands")
    safety_warning: Optional[str] = Field(None, description="Explicit warning on what NOT to do")


class RemediationReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    remediation_type: RemediationType = Field(RemediationType.NONE, description="Remediation approach type")
    playbook_match: bool = Field(False, description="Whether root cause cleanly matched an approved playbook")
    playbook_id: Optional[str] = Field(None, description="Playbook ID in PLAYBOOK_CATALOG.json")
    playbook_file: Optional[str] = Field(None, description="Relative path to playbook YAML")
    risk_level: Optional[str] = Field("low", description="Operational risk level of remediation")
    requires_human_approval: bool = Field(True, description="Strict requirement for human SRE gate")
    ansible_pseudocode: Optional[Union[list[str], str]] = Field(None, description="Day-1 Ansible YAML task spec")
    manual_cli_fallback: Optional[Union[ManualCLIFallback, dict[str, Any]]] = Field(None, description="Guarded CLI alternative")
    aap_launch_spec: Optional[dict[str, Any]] = Field(None, description="Ansible Automation Platform extra vars")
    verification_goal: Optional[str] = Field(None, description="Target post-remediation condition")


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hypothesis_id: str = Field(..., description="Unique hypothesis identifier")
    title: str = Field(..., description="Hypothesis description")
    status: str = Field(..., description="supported, contradicted, unresolved")
    confidence: Confidence = Field(..., description="high, medium, low")
    rationale: str = Field(..., description="Justification grounded in evidence")
    supporting_evidence_ids: list[str] = Field(default_factory=list, description="Cited supporting evidence IDs")
    contradicting_evidence_ids: list[str] = Field(default_factory=list, description="Cited contradicting evidence IDs")


class InvestigationReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = Field("1.0", description="Report contract schema version")
    investigation_id: Optional[str] = Field(None, description="Investigation run UUID")
    investigation_status: str = Field("completed", description="Lifecycle outcome of investigation")
    classification: Classification = Field(..., description="Overall diagnostic classification")
    confidence: Confidence = Field(..., description="Confidence level: high, medium, low")
    lifecycle_stage: Optional[str] = Field("drain", description="Evaluated node lifecycle stage")
    use_case_id: Optional[str] = Field(None, description="Diagnosed use case ID e.g. 01-pdb-eviction-blocked")
    stop_reason: Optional[str] = Field(None, description="Canonical stop reason code from contracts/REASON_CODES.md")
    target_context: Optional[TargetContext] = Field(None, description="Cluster, node, workload context")
    root_cause: Optional[RootCause] = Field(None, description="Root cause synthesis and evidence citations")
    remediation: RemediationReport = Field(default_factory=RemediationReport, description="Structured remediation output")
    hypotheses: list[Hypothesis] = Field(default_factory=list, description="Evaluated causal hypotheses")
    execution_timing_ms: dict[str, int] = Field(default_factory=dict, description="Performance latency timings")
    created_at: Optional[datetime] = Field(None, description="Report generation timestamp")

    @model_validator(mode="after")
    def validate_safety_and_remediation_policy(self) -> InvestigationReport:
        # Non-negotiable policy: No remediation allowed on inconclusive or not_supported
        if self.classification in (Classification.INCONCLUSIVE, Classification.NOT_SUPPORTED):
            if self.remediation.playbook_match:
                raise ValueError(f"playbook_match cannot be True when classification is {self.classification.value}")
            if self.remediation.playbook_id is not None:
                raise ValueError(f"playbook_id must be None when classification is {self.classification.value}")
        
        # Supported/high must not carry an inconclusive stop reason
        if self.classification == Classification.SUPPORTED and self.confidence == Confidence.HIGH:
            if self.stop_reason is not None:
                raise ValueError("supported/high finding must not carry a stop_reason")
        
        return self


class OracleOutput(BaseModel):
    """Simplified evaluation shape matching uc01_reference oracle."""
    model_config = ConfigDict(extra="ignore")

    classification: Classification
    confidence: Confidence
    sub_branch: Optional[str] = None
    stop_reason: Optional[str] = None
    remediation_kind: RemediationKind = RemediationKind.NONE
    playbook_id: Optional[str] = None
    extra_vars: Optional[dict[str, Any]] = None
