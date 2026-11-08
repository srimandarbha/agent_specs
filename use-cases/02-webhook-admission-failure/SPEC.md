# SPEC: Admission Webhook Blocks Pod Deletion or Eviction

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Problem Statement
The diagnostic agent must identify whether an OpenShift MCP/upgrade stall is caused by **admission webhook blocks pod deletion or eviction**, distinguish third-party webhook failures from the KubeVirt eviction interceptor, determine whether the failure is a crashed webhook controller, an expired TLS serving certificate, or a network policy timeout, and formulate an actionable remediation specification (manual CLI fallback) without direct cluster mutation.

## Trigger and Scope
- Lifecycle stage: **API Admission / Eviction Subresource**
- Trigger signal: MCC or API-server logs report: `(?i)(failed calling webhook|webhook.*denied.*eviction|admission webhook.*context deadline exceeded|x509: certificate.*webhook|connection refused.*webhook)` on a pod eviction request.
- In scope: Read-only evidence gathering from unified Splunk multi-index search/KV store, discriminating KubeVirt interceptor from general webhooks, causal classification, confidence reporting, safe manual CLI fallback runbook generation, and recovery verification.
- Out of scope: Deleting admission webhooks, patching `failurePolicy` autonomously, or bypassing cluster security controls.

## Required Telemetry Sources (Splunk Only)
* `index=ocp_logs`: Machine Config Controller drain logs, kube-apiserver admission logs, webhook controller logs.
* `index=k8s_objects` / KV Store:
  * `Pod` (`metadata.name`, `metadata.namespace`, `spec.nodeName`).
  * `Node` (`status.conditions`, `spec.unschedulable`).
  * `Event` (admission denial events, endpoint unready events).
* `index=ocp_metrics`: `apiserver_admission_webhook_rejection_count`, `apiserver_admission_webhook_admission_duration_seconds`.

## Diagnostic Strategy
1. **Perception:** Ingest unified Splunk dossier in a single round-trip.
2. **Discrimination Gate:** Verify whether the webhook is `virt-launcher-eviction-interceptor.kubevirt.io`:
   - If YES $\rightarrow$ Handoff to `05-ocv-vm-not-migratable`.
   - If NO $\rightarrow$ Continue webhook infrastructure triage.
3. **Causal Depth:** Determine *why* the webhook failed:
   - Did the webhook controller pod crash or report 0 ready endpoints? (Branch 3A).
   - Has the webhook server's TLS certificate expired? (Branch 3B).
   - Is an egress firewall or NetworkPolicy blocking apiserver-to-webhook traffic? (Branch 3C).

## Two-Tier Remediation Contract
1. **Playbook Matching (AAP / AWX):**
   - **Automated remediation is STRICTLY PROHIBITED** (`matched: false`). Admission webhooks enforce enterprise compliance and security controls; disabling or deleting them autonomously violates security boundaries.
2. **Targeted CLI Fallback (Human SRE Runbook):**
   - For crashed controllers: output deployment restart and log inspection commands.
   - For expired TLS certificates: output service-ca certificate regeneration steps.
   - For emergency bypass: output explicit, security-gated instructions to temporarily adjust `failurePolicy: Ignore` with required rollback steps.

## Safety Constraints
* NEVER delete `ValidatingWebhookConfiguration` or `MutatingWebhookConfiguration` objects from the agent.
* NEVER alter `failurePolicy` without workload and security owner sign-off.
* The agent has zero direct mutation tools.

## Success Criteria
The webhook service reports ready endpoints, the eviction subresource call succeeds with HTTP 200, and MCC logs record the node drain advancing.

---

## Agent Graph Integration Contract

This use case is invoked by the shared 10-node LangGraph workflow in `../../architecture/LANGGRAPH_DESIGN.md`.

### Bounded Execution
* Investigation Deadline: 45 seconds.
* Tool Budget: Max 2 Splunk tool calls per investigation.
* Output: Structured report with evidence citations and either an `aap_launch_spec` or `manual_cli_fallback`.
