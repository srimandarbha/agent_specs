# Design: Replacement Workloads Cannot Schedule After Eviction (`07-reschedule-capacity-affinity`)

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Design Objective
Diagnose **replacement workloads cannot schedule after eviction**, discriminate whether the scheduling barrier is compute capacity exhaustion, hard pod anti-affinity deadlock, or taint/topology pinning, and generate a validated manual CLI fallback runbook for cluster administrators without direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, cordoned node name, pending replacement pod identity, and incident time window.
   - Pinned OpenShift version (4.12+ / 4.16+ / 4.22+ / 5.0).
2. **Confirm Lifecycle Stage**
   - Eviction of the original pod succeeded on the draining node, but the replacement pod is stuck in `phase: Pending`.
   - Scheduler emits `FailedScheduling` events naming the pending pod.
3. **Execute Single Multi-Index Search**
   - Query `query_unified_splunk_dossier` across `index=ocp_logs`, `index=k8s_objects` / KV Store, and `index=ocp_metrics`.
4. **Causal Correlation & Classification**
   - Extract `FailedScheduling` events from `index=k8s_objects`.
   - Parse scheduler rejection:
     - If all uncordoned nodes lack allocatable CPU or RAM $\rightarrow$ **Branch 3A: Capacity Starvation**.
     - If `spec.affinity.podAntiAffinity` has `requiredDuringSchedulingIgnoredDuringExecution` matching sibling replicas on all candidate nodes $\rightarrow$ **Branch 3B: Hard Anti-Affinity Deadlock**.
     - If denial cites `untolerated taint` or `volume node affinity conflict` $\rightarrow$ **Branch 3C: Taint / Zone Affinity Mismatch**.
5. **Remediation Resolution**
   - Evaluate against `remediations/PLAYBOOK_CATALOG.json`.
   - Architectural and infrastructure capacity adjustments require explicit SRE human judgment $\rightarrow$ set `playbook_match: null`.
   - Synthesize targeted, copy-pasteable `manual_cli_fallback` runbooks with explicit pre-checks, commands, safety warnings, and post-verification checks.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Post-remediation verification: Replacement pods transition to `Running` / `Ready`, PDB disruption allowance is restored (`disruptionsAllowed > 0`), and MCO pool update advances.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> UNIFIED_DOSSIER_COLLECTED -> SCHEDULER_CONSTRAINT_DIAGNOSED -> MANUAL_CLI_FALLBACK_GENERATED -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `node_name`, `target_namespace`, `pending_pod_name`, `scheduler_reason`.
* **Evidence Citations:** `scheduler_failed_scheduling_event`, `node_allocatable_metrics`, `workload_affinity_spec`.
* **Remediation Specification:**
  ```json
  {
    "matched": false,
    "reason": "Hard pod anti-affinity deadlock or cluster compute capacity exhaustion requires infrastructure or application topology adjustment.",
    "manual_cli_fallback": {
      "risk_level": "medium",
      "pre_checks": [ ... ],
      "remediation_steps": [ ... ],
      "safety_warning": "...",
      "verification": [ ... ]
    }
  }
  ```

---

## Guardrails
- Strictly read-only execution in the diagnostic agent.
- No direct `oc` commands executed autonomously.
- No automated relaxing of application anti-affinity rules or scaling down of mission-critical stateful sets without workload owner sign-off.
- Credentials and secret environment variables are stripped before persistence.
