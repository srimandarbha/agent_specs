"""Comprehensive unit tests for Pydantic contracts in schemas/."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from schemas import (
    EventEnvelope,
    TriggerType,
    AlertDetails,
    RequestDetails,
    EvidenceRecord,
    EvidenceType,
    ResourceIdentifier,
    Freshness,
    Quality,
    MetricPayload,
    Dossier,
    DossierStatus,
    RelationshipRecord,
    RelationshipResult,
    AgentState,
    TrackType,
    LifecycleStage,
    InvestigationReport,
    Classification,
    Confidence,
    RemediationType,
    OracleOutput,
)

FX_01 = Path(__file__).resolve().parent / "fixtures" / "01-pdb-eviction-blocked"


def test_valid_alert_event():
    envelope = EventEnvelope(
        schema_version="1.0",
        event_id="evt-1234-abcd",
        event_type="com.example.openshift.mco.drain.alert",
        occurred_at=datetime(2026, 11, 8, 6, 30, tzinfo=timezone.utc),
        received_at=datetime(2026, 11, 8, 6, 30, 2, tzinfo=timezone.utc),
        trigger_type=TriggerType.ALERT,
        source="alertmanager",
        cluster_id="ocp-prod-01",
        cluster_name="ocp-prod-01",
        openshift_version="4.22.z",
        node_name="worker-01.example.invalid",
        mcp_name="worker",
        alert=AlertDetails(
            name="MachineConfigControllerDrainError",
            fingerprint="fp-stable-1",
            severity="warning",
            labels={"alertname": "MachineConfigControllerDrainError"},
            annotations={"description": "Eviction blocked by PDB"},
        ),
    )
    assert envelope.trigger_type == TriggerType.ALERT
    assert envelope.cluster_id == "ocp-prod-01"
    key = envelope.generate_idempotency_key()
    assert isinstance(key, str) and len(key) == 64


def test_valid_manual_event():
    envelope = EventEnvelope(
        schema_version="1.0",
        event_id="evt-5678-efgh",
        event_type="com.example.openshift.mco.drain.manual",
        occurred_at=datetime(2026, 11, 8, 7, 0, tzinfo=timezone.utc),
        received_at=datetime(2026, 11, 8, 7, 0, 1, tzinfo=timezone.utc),
        trigger_type=TriggerType.MANUAL,
        source="cli",
        cluster_id="ocp-prod-01",
        cluster_name="ocp-prod-01",
        openshift_version="4.22.z",
        node_name="worker-02.example.invalid",
        mcp_name="worker",
        request=RequestDetails(
            requested_by="sre-alice",
            text="Node worker-02 stuck in drain for 40 minutes",
            change_id="CHG-9988",
        ),
    )
    assert envelope.trigger_type == TriggerType.MANUAL
    assert envelope.request.requested_by == "sre-alice"


def test_invalid_event_trigger_consistency():
    # Alert without alert details
    with pytest.raises(ValidationError, match="requires an 'alert' payload"):
        EventEnvelope(
            schema_version="1.0",
            event_id="evt-bad-1",
            event_type="com.example.alert",
            occurred_at=datetime.now(timezone.utc),
            received_at=datetime.now(timezone.utc),
            trigger_type=TriggerType.ALERT,
            source="alertmanager",
            cluster_id="ocp-prod-01",
            cluster_name="ocp-prod-01",
            openshift_version="4.22.z",
            node_name="worker-01",
            mcp_name="worker",
            alert=None,
        )

    # Manual without requested_by
    with pytest.raises(ValidationError, match="requires an authenticated principal"):
        EventEnvelope(
            schema_version="1.0",
            event_id="evt-bad-2",
            event_type="com.example.manual",
            occurred_at=datetime.now(timezone.utc),
            received_at=datetime.now(timezone.utc),
            trigger_type=TriggerType.MANUAL,
            source="cli",
            cluster_id="ocp-prod-01",
            cluster_name="ocp-prod-01",
            openshift_version="4.22.z",
            node_name="worker-01",
            mcp_name="worker",
            request=RequestDetails(text="Stuck drain"),
        )


def test_evidence_record_validation():
    ev = EvidenceRecord(
        evidence_id="ev-001",
        source_adapter="splunk_mcp",
        source_dataset="k8s_objects",
        source_query_id="qry-splunk-101",
        cluster_id="ocp-prod-01",
        resource=ResourceIdentifier(
            api_version="policy/v1",
            kind="PodDisruptionBudget",
            namespace="payments",
            name="payments-api-pdb",
            uid="uid-pdb-123",
        ),
        evidence_type=EvidenceType.OBJECT_SNAPSHOT,
        event_time=datetime(2026, 11, 8, 9, 20, tzinfo=timezone.utc),
        observed_at=datetime(2026, 11, 8, 9, 20, 2, tzinfo=timezone.utc),
        ingested_at=datetime(2026, 11, 8, 9, 20, 5, tzinfo=timezone.utc),
        retrieved_at=datetime(2026, 11, 8, 9, 20, 10, tzinfo=timezone.utc),
        freshness=Freshness.FRESH,
        quality=Quality.VALID,
        fields={"disruptions_allowed": 0, "min_available": 2},
        excerpt="PodDisruptionBudget spec: minAvailable=2 status: disruptionsAllowed=0",
    )
    assert ev.resource.kind == "PodDisruptionBudget"
    assert ev.fields["disruptions_allowed"] == 0


def test_metric_payload_validation():
    metric = MetricPayload(
        metric_name="kube_pod_disruption_budget_status_pod_disruptions_allowed",
        labels={"namespace": "payments", "poddisruptionbudget": "payments-api-pdb"},
        value=0.0,
        sample_timestamp=datetime.now(timezone.utc),
        aggregation_window="1m",
    )
    assert metric.value == 0.0
    assert metric.labels["namespace"] == "payments"


def test_parse_golden_dossier_fixture():
    golden_path = FX_01 / "golden_dossier.json"
    data = json.loads(golden_path.read_text())
    dossier = Dossier.model_validate(data)
    assert dossier.status == DossierStatus.OK
    assert len(dossier.records) == 1
    r = dossier.records[0]
    assert r["cluster_id"] == "ocp-prod-01"
    assert r["pdb_details"]["disruptions_allowed"] == 0


def test_parse_golden_expected_output_report():
    expected_path = FX_01 / "expected_output.json"
    data = json.loads(expected_path.read_text())
    report = InvestigationReport.model_validate(data)
    assert report.classification == Classification.SUPPORTED
    assert report.confidence == Confidence.HIGH
    assert report.remediation.playbook_match is True
    assert report.remediation.playbook_id == "playbook_pdb_scale_up"
    assert report.target_context.target_namespace == "payments"


def test_report_safety_interlock():
    # Inconclusive must not have playbook match
    with pytest.raises(ValidationError, match="playbook_match cannot be True"):
        InvestigationReport(
            classification=Classification.INCONCLUSIVE,
            confidence=Confidence.LOW,
            remediation={"playbook_match": True, "playbook_id": "playbook_pdb_scale_up"},
        )

    # Supported/high must not carry stop_reason
    with pytest.raises(ValidationError, match="supported/high finding must not carry a stop_reason"):
        InvestigationReport(
            classification=Classification.SUPPORTED,
            confidence=Confidence.HIGH,
            stop_reason="contradictory_telemetry",
            remediation={"playbook_match": False},
        )


def test_oracle_output_schema():
    oracle_data = {
        "classification": "not_supported",
        "confidence": "high",
        "sub_branch": None,
        "stop_reason": "pdb_disruptions_allowed_positive",
        "remediation_kind": "none",
        "playbook_id": None,
    }
    out = OracleOutput.model_validate(oracle_data)
    assert out.classification == Classification.NOT_SUPPORTED
    assert out.stop_reason == "pdb_disruptions_allowed_positive"


def test_agent_state_initialization():
    now = datetime.now(timezone.utc)
    state = AgentState(
        investigation_id="inv-001",
        idempotency_key="idemp-key-1",
        event_id="evt-001",
        cluster_id="ocp-prod-01",
        cluster_name="ocp-prod-01",
        openshift_version="4.22.z",
        node_name="worker-01",
        mcp_name="worker",
        started_at=now,
        deadline_at=now,
        track=TrackType.TRACK_A,
        lifecycle_stage=LifecycleStage.DRAIN,
    )
    assert state.query_count_by_adapter["splunk_mcp"] == 0
    assert state.track == TrackType.TRACK_A
