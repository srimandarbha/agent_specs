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
