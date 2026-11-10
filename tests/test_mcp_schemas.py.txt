"""Tests validating MCP tool schemas and sample telemetry responses."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from schemas import Dossier, DossierStatus

REPO = Path(__file__).resolve().parent.parent
MCP_SCHEMAS_DIR = REPO / "contracts" / "mcp_schemas"
SAMPLES_DIR = REPO / "contracts" / "samples"


def test_splunk_mcp_tools_schema_validity():
    schema_path = MCP_SCHEMAS_DIR / "splunk_mcp_tools.json"
    assert schema_path.is_file()
    data = json.loads(schema_path.read_text())
    assert "tools" in data
    tool_names = {t["name"] for t in data["tools"]}
    expected_tools = {
        "query_splunk_dossier",
        "k8s_live_inventory_lookup",
        "query_broad_anomaly_dossier",
    }
    assert expected_tools == tool_names
    for t in data["tools"]:
        assert "parameters" in t
        assert t["parameters"]["type"] == "object"
        assert "cluster_id" in t["parameters"]["properties"]
    inventory = next(t for t in data["tools"] if t["name"] == "k8s_live_inventory_lookup")
    ip = inventory["parameters"]
    assert set(ip["required"]) == {"cluster_id", "kind"}
    assert "name" not in ip["required"]
    assert ip["properties"]["lookup_mode"]["enum"] == ["exact", "list"]
    kinds = set(ip["properties"]["kind"]["enum"])
    assert {"Lease", "CSINode", "ClusterOperator", "EndpointSlice", "DaemonSet"} <= kinds


def test_prometheus_mcp_tools_schema_validity():
    schema_path = MCP_SCHEMAS_DIR / "prometheus_mcp_tools.json"
    assert schema_path.is_file()
    data = json.loads(schema_path.read_text())
    assert "tools" in data
    tool_names = {t["name"] for t in data["tools"]}
    expected_tools = {
        "query_prometheus_instant",
        "query_prometheus_range",
    }
    assert expected_tools == tool_names
    for t in data["tools"]:
        assert "parameters" in t
        assert "cluster_id" in t["parameters"]["properties"]


def test_splunk_unified_dossier_sample():
    sample_path = SAMPLES_DIR / "splunk_unified_dossier_response.json"
    assert sample_path.is_file()
    data = json.loads(sample_path.read_text())
    # Should parse into Pydantic Dossier model
    dossier = Dossier.model_validate(data)
    assert dossier.status == DossierStatus.OK
    assert len(dossier.records) == 1
    assert dossier.records[0]["cluster_id"] == "ocp-prod-01"


def test_splunk_kv_lookup_sample():
    sample_path = SAMPLES_DIR / "splunk_kv_lookup_response.json"
    assert sample_path.is_file()
    data = json.loads(sample_path.read_text())
    assert data["status"] == "ok"
    assert data["lookup_table"] == "k8s_live_inventory_lookup"
    assert data["result"]["status"]["disruptionsAllowed"] == 0


def test_splunk_broad_anomaly_sample():
    sample_path = SAMPLES_DIR / "splunk_broad_anomaly_response.json"
    assert sample_path.is_file()
    data = json.loads(sample_path.read_text())
    assert data["track"] == "track_b"
    assert len(data["records"]) == 3


def test_prometheus_samples():
    instant_path = SAMPLES_DIR / "prometheus_instant_response.json"
    assert instant_path.is_file()
    data = json.loads(instant_path.read_text())
    assert data["status"] == "success"
    assert data["data"]["resultType"] == "vector"

    range_path = SAMPLES_DIR / "prometheus_range_response.json"
    assert range_path.is_file()
    rdata = json.loads(range_path.read_text())
    assert rdata["status"] == "success"
    assert rdata["data"]["resultType"] == "matrix"


def test_adapter_error_503_sample():
    error_path = SAMPLES_DIR / "adapter_error_503_response.json"
    assert error_path.is_file()
    data = json.loads(error_path.read_text())
    assert data["status"] == "error"
    assert data["error_code"] == "BACKEND_SERVICE_UNAVAILABLE"
