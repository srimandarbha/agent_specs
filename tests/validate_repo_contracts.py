#!/usr/bin/env python3
"""Basic structural checks for repository metadata and catalog references."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import re

REPO = Path(__file__).resolve().parents[1]

def main() -> int:
    errors: list[str] = []
    manifest = json.loads((REPO / "manifest.json").read_text(encoding="utf-8"))
    catalog = json.loads((REPO / "remediations/PLAYBOOK_CATALOG.json").read_text(encoding="utf-8"))
    if not isinstance(catalog, list):
        errors.append("PLAYBOOK_CATALOG.json must be a JSON array")
        catalog = []
    expected_evidence = {"splunk_mcp", "prometheus_mcp"}
    actual_evidence = set(manifest.get("operating_decisions", {}).get("evidence", []))
    if actual_evidence != expected_evidence:
        errors.append(f"manifest evidence adapters {sorted(actual_evidence)} != {sorted(expected_evidence)}")
    ids = {case.get("id") for case in manifest.get("use_cases", [])}
    if len(ids) != 16:
        errors.append(f"manifest declares {len(ids)} use cases, expected 16")
    for rel in manifest.get("shared_contracts", {}).values():
        if not (REPO / rel).is_file():
            errors.append(f"missing shared contract: {rel}")
    # Every skill must carry machine-readable metadata before the loader can activate it.
    skill_files = sorted((REPO / "use-cases").glob("*/skill.md"))
    if len(skill_files) != 16:
        errors.append(f"found {len(skill_files)} skill.md files, expected 16")
    for skill_file in skill_files:
        content = skill_file.read_text(encoding="utf-8")
        if not content.startswith("---\n"):
            errors.append(f"{skill_file.relative_to(REPO)} is missing YAML front matter")
            continue
        end = content.find("\n---\n", 4)
        if end < 0:
            errors.append(f"{skill_file.relative_to(REPO)} has unterminated YAML front matter")
            continue
        front = content[4:end]
        skill_id = re.search(r"(?m)^skill_id:\s*(\S+)\s*$", front)
        status = re.search(r"(?m)^status:\s*(\S+)\s*$", front)
        if not skill_id or skill_id.group(1) != skill_file.parent.name:
            errors.append(f"{skill_file.relative_to(REPO)} skill_id does not match directory")
        if not status or status.group(1).strip() not in {"draft", "candidate", "active", "deprecated"}:
            errors.append(f"{skill_file.relative_to(REPO)} has missing/invalid lifecycle status")

    # Ensure the inventory contract can represent every object required by the matrix.
    splunk_schema = json.loads((REPO / "contracts/mcp_schemas/splunk_mcp_tools.json").read_text(encoding="utf-8"))
    inventory = next((t for t in splunk_schema.get("tools", []) if t.get("name") == "k8s_live_inventory_lookup"), {})
    params = inventory.get("parameters", {})
    props = params.get("properties", {})
    supported_kinds = set(props.get("kind", {}).get("enum", []))
    matrix = (REPO / "docs/OBSERVABILITY_MATRIX.md").read_text(encoding="utf-8")
    required_kinds = {
        "Pod", "Node", "Event", "PodDisruptionBudget", "Lease", "VolumeAttachment",
        "PersistentVolumeClaim", "PersistentVolume", "CSINode", "MachineConfigPool",
        "MachineConfig", "ClusterOperator", "Service", "EndpointSlice",
        "ValidatingWebhookConfiguration", "MutatingWebhookConfiguration", "Deployment",
        "ReplicaSet", "DaemonSet", "CertificateSigningRequest", "VirtualMachineInstance",
        "VirtualMachineInstanceMigration",
    }
    missing_kinds = required_kinds - supported_kinds
    if missing_kinds:
        errors.append(f"inventory schema missing observability kinds: {sorted(missing_kinds)}")
    if set(params.get("required", [])) != {"cluster_id", "kind"}:
        errors.append("inventory schema must permit bounded list lookup without requiring name")
    if "name" in params.get("required", []):
        errors.append("inventory schema incorrectly requires name for list lookup")

    catalog_ids = {p.get("playbook_id") for p in catalog}
    required = {"playbook_restart_csi_driver", "playbook_restart_failed_systemd_unit"}
    if not required.issubset(catalog_ids):
        errors.append(f"catalog missing required playbooks: {sorted(required - catalog_ids)}")
    csi = next((p for p in catalog if p.get("playbook_id") == "playbook_restart_csi_driver"), {})
    if "03-pod-termination-finalizer" not in csi.get("supported_use_cases", []):
        errors.append("CSI restart catalog mapping does not include UC03")
    systemd = next((p for p in catalog if p.get("playbook_id") == "playbook_restart_failed_systemd_unit"), {})
    if not systemd.get("service_profiles"):
        errors.append("systemd restart catalog has no service-specific risk profiles")
    if errors:
        for e in errors:
            print("ERROR:", e)
        return 1
    print("Repository metadata and catalog structure: PASS")
    print("This does not replace runtime, schema, integration or safety evaluation.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
