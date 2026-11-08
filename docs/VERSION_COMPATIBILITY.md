# Version Compatibility and Source Validation

## Purpose

A diagnosis skill is valid only for the OpenShift/MCO/KubeVirt/CSI versions against which its assumptions, fields, metrics, log signatures and procedures have been checked. Upstream `main` is a research source, not proof of behavior in a released cluster.

## Compatibility record

For every skill release, record:

- OpenShift versions tested (exact z-streams where relevant)
- MCO image digest/source tag and commit
- KubeVirt / OpenShift Virtualization operator version where applicable
- CSI driver name, version, topology and documented attach limit source
- Prometheus metric name, labels, type, unit and first/last verified version
- Kubernetes API group/version and required fields
- Red Hat runbook/solution URL and last verification date
- known deviations, deprecations and unsupported branches
- fixture/evaluation revision proving the skill behavior

## Release gates

1. Resolve the actual MCO source tag corresponding to the deployed OpenShift release.
2. Compare controller/daemon implementation and matching tests; do not copy `main` constants into production logic.
3. Verify Red Hat alert runbook and product documentation for the release.
4. Check API field existence and version changes (for example, policy/v1 PDBs and CSI objects).
5. Verify every Prometheus metric exists in the target platform and has the expected labels/semantics. Metrics such as `kubevirt_vmi_non_evictable` or MCO-specific metrics must not be assumed across all versions without discovery.
6. Test log signatures against captured, sanitized examples from the supported release.
7. Mark unsupported versions explicitly; route to `inconclusive: version_gate_failed` rather than silently running an unverified skill.

## Evidence provenance

Store URLs, upstream commit/tag, access date, reviewer, version range and a short rationale in skill metadata or verified `sre_knowledge`. Do not cite moving `latest` documentation as the only source for a pinned release decision.
