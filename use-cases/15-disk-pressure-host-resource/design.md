# Design: Node Disk Pressure or Host Resource Exhaustion (`15-disk-pressure-host-resource`)

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

## Design Objective
Diagnose **node disk pressure, ephemeral storage exhaustion, or PID saturation**, isolate the affected host filesystem mount (`/`, `/var`, `/var/lib/containers`, `/var/lib/kubelet`) or kernel process table, and generate a safe, non-destructive manual CLI fallback runbook for cluster administrators without direct cluster mutation.

---

## Evidence-First Flow

1. **Establish Identity & Context**
   - Cluster ID, MachineConfigPool, target node name, and incident time window.
   - Pinned OpenShift version (4.12+ / 4.16+ / 4.22+ / 5.0).
2. **Confirm Lifecycle Stage**
   - Active stage: Node drain, MCD apply, or node readiness check.
   - Trigger signal: Node object condition `DiskPressure: True` or `PIDPressure: True`, or Kubelet/MCD write error logs.
3. **Execute Federated Evidence Queries**
   - Query `query_splunk_dossier` for `index=ocp_logs` and `index=k8s_objects` / KV Store; query metrics separately through Prometheus MCP.
4. **Causal Correlation & Classification**
   - Correlate `Node` conditions with Kubelet error logs and disk mount metrics.
   - Parse specific failure mode:
     - If `/var/lib/containers` is full and Kubelet logs cite `ImageGCFailed` $\rightarrow$ **Branch 3A: CRI-O Image Store Exhaustion**.
     - If `/` or `/var` is full and MCD logs cite `write /etc/...: no space left on device` $\rightarrow$ **Branch 3B: Host Systemd Journal / Log Exhaustion**.
     - If `/var/lib/kubelet` emptyDir is exhausted by a workload pod $\rightarrow$ **Branch 3C: Ephemeral Storage Quota Exhaustion**.
     - If `PIDPressure: True` and process count approaches `pid_max` $\rightarrow$ **Branch 3D: Host PID Table Exhaustion**.
5. **Remediation Resolution**
   - Evaluate against `remediations/PLAYBOOK_CATALOG.json`.
   - Host filesystem and cgroup operations carry severe operational risk $\rightarrow$ set `playbook_match: null`.
   - Synthesize targeted, copy-pasteable `manual_cli_fallback` runbooks containing exact node debug commands (`oc debug node/...`), runtime tools (`crictl rmi --prune`, `journalctl --vacuum-size`), and safety warnings.
6. **Persist & Verify**
   - Record investigation state and evidence IDs in PostgreSQL (`db/migrations/001_initial.sql`).
   - Post-remediation verification: Node conditions `DiskPressure: False` and `PIDPressure: False`, node `Ready: True`, and MCD transitions to `Done`.

---

## State Model
`TRIGGERED -> CONTEXT_CAPTURED -> EVIDENCE_COLLECTED -> RESOURCE_PRESSURE_DIAGNOSED -> MANUAL_CLI_FALLBACK_GENERATED -> PERSISTED`

---

## Data Contract
* **Investigation Record:** `investigation_id`, `cluster_id`, `node_name`, `target_filesystem`, `pressure_type`, `kubelet_error_excerpt`.
* **Evidence Citations:** `node_pressure_conditions`, `kubelet_gc_error_log`, `mcd_write_error_log`, `node_filesystem_metrics`.
* **Remediation Specification:**
  ```json
  {
    "matched": false,
    "reason": "Host disk space or process table exhausted; requires guarded node debug cleanup via container runtime or systemd vacuum.",
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
- No autonomous `rm -rf` or file manipulation on host filesystems.
- Autonomous deletion of CRI-O backing files is strictly forbidden; runtime metadata must remain consistent.
- Passwords and auth tokens are scrubbed before persistence.
