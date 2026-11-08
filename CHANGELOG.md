## Unreleased - feature branch contract reconciliation

- Replaced the stale Splunk-only, single multi-index architecture in `intent.md` with the federated Splunk MCP + Prometheus MCP design declared by `manifest.json`.
- Rewrote the logical evidence tool contracts and clarified that logical operation names must be mapped to actual discovered MCP server tools during integration.
- Expanded the Splunk inventory contract to support the observability matrix object kinds and bounded exact/list lookup semantics.
- Added machine-readable YAML front matter to all 16 skills. All remain `draft` until fixture coverage, domain review and evaluation gates pass.
- Strengthened repository validation and MCP schema tests for skill metadata and inventory-kind coverage.
- Preserved the known evaluation-fixture gap rather than creating empty or synthetic fixture files that would falsely imply test coverage.

# Update changelog

## 2026-11-08: Shared agent contracts and implementation readiness

- Added repository gap analysis and development blueprint.
- Added event, evidence schema, MCP adapter and deterministic correlation contracts.
- Replaced fixed Golden Six language with a common baseline plus per-use-case object requirements; documented missing Lease, CSINode, ClusterOperator, Services/EndpointSlices, DaemonSet, workload controllers, storage claims/volumes and conditional VMI state.
- Clarified default split Splunk MCP + Prometheus MCP topology and corrected query budget/latency assumptions.
- Added cluster registry, skill loader, model/prompt policy, security, version compatibility, deployment and agent observability contracts.
- Added remediation recommendation/AAP handoff lifecycle and corrected UC03 catalog mapping plus service-specific systemd risk profiles.
- Added additive PostgreSQL migration for structured recommendations, approvals/external execution references and investigation audit events.
- Added executable evaluation backlog; did not fabricate missing fixture datasets or claim that documented evals are already implemented.
- No changes have been pushed to GitHub; apply on a feature branch and review before merging.
