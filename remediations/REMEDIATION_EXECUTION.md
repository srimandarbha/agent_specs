# Remediation Recommendation and AAP Handoff Contract

## Phase boundary

### Day 1: recommendation only

The agent returns a typed recommendation matching a reviewed catalog entry or a manual CLI runbook. It does not execute a playbook, call the AAP launch API, or possess AAP launch credentials. YAML shown in a report is pseudocode and must be labelled non-executable until an actual playbook artifact is reviewed and version-pinned.

### Later phase: separately controlled AAP service

A dedicated integration service may accept a recommendation only when it has a valid catalog revision, approved job-template mapping, required evidence, validated extra variables, approver identity, change/ticket reference and policy approval. It must not accept arbitrary playbook paths or arbitrary template IDs from the LLM.

## Recommendation payload

Required fields: `recommendation_id`, `investigation_id`, `cluster_id`, `use_case_id`, `diagnosis_status`, `confidence`, `playbook_match`, `playbook_id`, `catalog_revision`, `playbook_artifact_revision`, `risk_level`, `requires_human_approval`, `preconditions_checked[]`, `missing_preconditions[]`, `aap_job_template_id` (only in enabled AAP phase), `aap_extra_vars`, `manual_cli_fallback`, `verification_goal`, and evidence IDs supporting every precondition.

Exactly one of `playbook_spec` or `manual_cli_fallback` may be active. No match means `playbook_match=false` and `playbook_id=null`. Track B must always use no-match.

## Mandatory gates

1. Diagnosis must be `supported` with the required confidence threshold defined by the catalog entry.
2. All playbook preconditions must be proven by fresh, same-cluster evidence.
3. Every required extra variable must be present and type-validated; reject unknown variables.
4. The playbook ID and catalog revision must match an allowlisted immutable catalog revision.
5. High-risk/disruptive actions require explicit workload/service owner and change approval; policy may prohibit automation altogether.
6. Human approval must bind to exact cluster, target, playbook/template, extra_vars hash and expiration time. A later payload change invalidates approval.
7. The execution service uses its own scoped identity and logs AAP job ID, launch principal, approval, status and timestamps.
8. Post-execution verification is a separate read-only investigation. A successful AAP job does not prove cluster recovery.

## Failure handling

Reject stale recommendations, catalog drift, missing target identity, unknown job template, approval mismatch, unsupported OpenShift version or failed preconditions. Never retry a non-idempotent remediation launch blindly. Use an idempotency key at the AAP boundary and reconcile job status before retrying.

## Catalog corrections required

- UC03 may delegate to `playbook_restart_csi_driver` only for an explicitly proven CSI node daemon/RPC failure, never for generic finalizer removal. Add UC03 to that playbook's supported-use-case mapping.
- `playbook_restart_failed_systemd_unit` must define an explicit per-service allowlist and separate risk/precondition profiles. `kubelet` and `crio` are critical platform services and must not inherit a “non-critical service” low/medium policy without a dedicated approval profile.
- AAP artifact paths in `PLAYBOOK_CATALOG.json` are references, not evidence that YAML exists. Pin the external repository and commit before enabling launches.
