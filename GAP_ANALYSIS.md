# Repository Gap Analysis

**Baseline reviewed:** `main` at `c7b7cbea4c2d579468c5c1bf5facbf0838a5a464` (2026-11-08)

## Executive assessment

The repository is a substantial design and domain-knowledge pack for a read-only MCO/MCP troubleshooting agent. It is not yet an implementation-ready or production-operational specification. The 16 scenario packs establish useful diagnostic intent, branching, safety boundaries, and desired evaluation behavior. The remaining work is concentrated in shared contracts and executable engineering assets.

## Findings and priority

| Priority | Finding | Consequence | Required action |
|---|---|---|---|
| P0 | `manifest.json` lists only `splunk_mcp`, while the actual environment has separate Splunk and Prometheus MCP evidence paths | Runtime cannot satisfy all stated metric evidence requirements through the declared integration | Define independent adapters and a canonical dossier; allow Splunk-centralized metrics only as a deployment option |
| P0 | The so-called Golden Six list has seven entries; multiple use cases require objects not collected by the shown receiver config | Several diagnostic branches cannot be proven from collected data | Replace fixed Golden Six with a common baseline plus a per-use-case allowlist |
| P0 | Unified SPL example groups dissimilar resources by target resource and does not demonstrate valid Pod-to-PDB or workload-to-storage joins | Aggregation can separate related records or imply correlations that were never established | Retrieve bounded raw evidence, normalize it, and perform deterministic joins in a correlation engine |
| P0 | `eval.md` files reference roughly 80 input fixture paths, but only three referenced dossier files exist in the reviewed tree | The evaluation framework is mostly a blueprint; broad scenario regression cannot run | Create the referenced fixtures or amend each evaluation to reference existing canonical fixtures; add pytest harnesses |
| P0 | Catalog and scenario contracts disagree: UC03 references the CSI restart playbook but the catalog omits UC03; UC08 expects kubelet restart without a precise service allowlist | A playbook could be rejected incorrectly or matched for a service outside an agreed safety policy | Align catalog use-case mappings, service allowlist, preconditions, and service-specific risk |
| P1 | The catalog references playbook YAML paths that are not present in this repository | Catalog entries are specifications, not runnable playbooks | Keep Day-1 clearly pseudocode-only; define external repository, immutable revision, job template IDs, and later artifact verification |
| P1 | Object timestamp/freshness semantics are described inconsistently (`-1h`, `-24h`, and 10-minute KV refresh) | Stale inventory may be mistaken for current state | Define event, observed, ingested and snapshot times plus explicit per-object freshness limits |
| P1 | Existing SQL permits `kubernetes_api` as an evidence source although this agent is specified to have no Kubernetes API tool | Database history can misrepresent the deployed evidence boundary | Use source names for actual adapters and enforce deployment-specific source allowlists |
| P1 | Recommendation persistence has no structured catalog revision, approval, AAP correlation, or execution result fields | Recommendation-to-execution audit trail is incomplete | Add an additive migration for structured payload and external execution references; agent remains unable to execute mutations |
| P1 | No complete event, cluster registry, skill loader, model policy, deployment, security, or agent observability contracts | Teams must invent cross-cutting runtime behavior during coding | Add shared contracts before the first vertical slice |
| P2 | Version caveats are present, but there is no central compatibility/deprecation matrix | Upstream `main` assumptions may leak into a released cluster procedure | Pin OpenShift, MCO, KubeVirt and CSI evidence rules to tested versions |
| P2 | Track B unknown-anomaly handling has a useful one-shot bound but lacks a formal output schema and explicit evidence-quality gates | Unknown results may vary in shape and become difficult to evaluate | Define exploratory output as a strict schema with no playbook match and mandatory uncertainty language |

## Confirmed scope

The reviewed manifest declares 16 use cases: PDB eviction, webhook admission, finalizers, storage detach, non-migratable VM, stale virt-launcher, rescheduling, kubelet/CRI-O, API/etcd latency, MCP pause, MCD drift, render/apply, OS pivot/reboot, drain annotation coordination, disk/PID pressure, and CSI volume limits.

The repository includes shared LangGraph design, tool contracts, a PostgreSQL initial migration, observability documents, remediation catalog, testing strategy, evaluation framework, and per-use-case SPEC/design/plan/skill/eval documents. At the reviewed baseline, only three input dossier files referenced by the per-use-case eval documents were present (UC01 canonical and negative, UC16 fleet exhaustion); other references must be materialized before the stated coverage can run. Those existing assets are retained; this update adds shared contracts and corrects identified cross-document gaps.

## Readiness decision

- **Domain design:** strong foundation.
- **Implementation readiness:** conditional; do not implement all 16 scenarios independently yet.
- **First vertical slice:** UC01 only after the P0 evidence contract, one complete golden dossier, executable tests, and adapter contract are agreed.
- **Production readiness:** not established by Markdown completeness. It requires code, integration tests, load tests, security review, version-matched source validation, deployment evidence, and operational acceptance.

## Important non-goals

This update does not enable direct Kubernetes mutation, automatically launch AAP jobs, claim that the current MCP tools expose fields not demonstrated in their contracts, or certify the technical accuracy of every version-specific MCO/KubeVirt/CSI rule. Those require implementation and release-matched validation.
