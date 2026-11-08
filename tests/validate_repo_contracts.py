#!/usr/bin/env python3
"""Basic structural checks for repository metadata and catalog references."""
from __future__ import annotations
import json
from pathlib import Path
import sys

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
