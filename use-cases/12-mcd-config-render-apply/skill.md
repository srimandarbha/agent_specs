# Skill: Fail-Proof Diagnosis for Rendered MachineConfig or Configuration Apply Failure (`12-mcd-config-render-apply`)

<!-- precedence-note-2026-11-08 -->
> **Precedence note (2026-11-08):** wording in this file that assumes a single Splunk query, Splunk-only evidence, a "2 Splunk calls" budget, a 10-node graph or a fixed "Golden Six" object list is superseded by [`intent.md` §8](../../intent.md), [`LANGGRAPH_DESIGN.md` §11](../../architecture/LANGGRAPH_DESIGN.md), [`contracts/`](../../contracts) and [`OBSERVABILITY_MATRIX.md`](../../docs/OBSERVABILITY_MATRIX.md). Diagnostic decision logic is unchanged. Freshness limits come from the matrix, not from this file.

**Version:** 2.0.0  
**Target Environment:** OpenShift 4.12+ / 4.16+ / 4.22+ / 5.0  
**Execution Context:** LangGraph Deterministic Diagnostic Node (`load_skill` -> `assess_evidence` -> `diagnose` -> `match_remediation_plan`)  
**Evidence Source:** Unified Splunk Multi-Index Search (`ocp_logs`, `k8s_objects` / KV Store, `ocp_metrics`)

---

## 1. Entry Gate & Activation Criteria (Fail-Safe Pre-Checks)

The agent MUST verify these conditions before activating this skill. If any check fails, immediately exit to `persist_and_report` with the stated status.

| Check | Requirement | Exit Action on Failure |
|---|---|---|
| **Cluster Identity** | Target `cluster_id` matches an authorized cluster in the registry. | Exit: `inconclusive: invalid_cluster_context` |
| **Lifecycle Stage** | MachineConfigPool is in config generation or Node is in post-drain apply phase (`state: Working` or `state: Degraded`). | Exit: `inconclusive: lifecycle_stage_not_apply` |
| **Trigger Signal** | MCC or MCD logs match: `(?i)(failed to render.*machineconfig|conflicting file.*in machineconfigs|error merging machineconfigs|failed to apply update|error writing file.*ignition|failed to reload systemd)` OR MCP condition `RenderDegraded` is `True` OR Node annotation `state` is `Degraded` with reason `FailedToApply`. | Exit: `not_supported: no_render_or_apply_error_logged` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Ingest MCP & Node Apply State]       [No Render/Apply Error]
            Check RenderDegraded condition & MCD logs     ──► Exit: not_supported
                         │
                         ▼
            [Step 2: Differentiate Render vs Apply Failure]
            Check failure location: Controller vs Node
                         │
         ┌───────────────┴───────────────────────────────┐
         ▼                                               ▼
  [Render-Time Conflict]                         [Node Apply Failure]
  MCP condition RenderDegraded: True             Rendered config exists; MCD
  MCC logs: conflicting file in MCs              fails writing file/systemd on host
         │                                               │
         ▼                                               ▼
  Branch 3A: MachineConfig                       Branch 3B: Host Disk / Permission /
  Merge Collision                                SELinux Apply Failure
```

### Step 1: Ingest MCP Condition & Node State
1. In `k8s_objects` / KV Store, inspect the target `MachineConfigPool`:
   * Check `status.conditions[?(@.type=="RenderDegraded")].status` and `message`.
   * Check `status.conditions[?(@.type=="Degraded")].status` and `reason`.
   * Record `spec.configuration.name` (the target rendered config).
2. If target node is specified, inspect target `Node` object:
   * Record annotation `machineconfiguration.openshift.io/state`.
   * Record annotation `machineconfiguration.openshift.io/reason`.

### Step 2: Differentiate Controller Render vs. Host Node Apply
1. **Case 2A: Render-Time Failure in MCC (Controller Level):**
   * If MCP condition `RenderDegraded == True` OR MCC logs in `index=ocp_logs` show:
     ```regex
     (?i)failed to render.*machineconfig.*conflicting file "(?<conflicting_filepath>[^"]+)" in "(?<mc_a>[^"]+)" and "(?<mc_b>[^"]+)"
     ```
   * Proceed to **Branch 3A**.
2. **Case 2B: Configuration Apply Failure in MCD (Host Node Level):**
   * If target rendered MachineConfig exists, but MCD pod on the node logs:
     ```regex
     (?i)failed to apply update: error writing file "(?<failed_filepath>[^"]+)": (?<error_msg>.*)
     ```
     OR
     ```regex
     (?i)failed to reload systemd units: (?<error_msg>.*)
     ```
   * Proceed to **Branch 3B**.
3. **Case 2C: Ignition Version / Unsupported Feature Syntax:**
   * If MCC logs report `unsupported ignition version` or `invalid schema`: Proceed to **Branch 3C**.

---

## 3. Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                            [MachineConfig Failure]
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            ▼                          ▼                          ▼
  [Branch 3A: Render Conflict] [Branch 3B: Node Apply Error] [Branch 3C: Invalid Ignition]
  Two MachineConfigs define    Disk full, read-only host,     Unsupported spec version or
  same file path differently   or SELinux write denial        malformed storage syntax
            │                          │                          │
            ▼                          ▼                          ▼
  Playbook: null (Source Git)  Playbook: null (Host Risk)     Playbook: null (Syntax Error)
  CLI Fallback: Resolve MC     CLI Fallback: Fix Local Disk   CLI Fallback: Fix MachineConfig
```

* **Branch 3A: Render-Time MachineConfig Merge Conflict (Duplicate Path Collision)**
  * *Evidence:* MCP condition `RenderDegraded: True`; MCC logs report: `error merging machineconfigs: conflicting file /etc/... in 99-worker-custom-a and 99-worker-custom-b`.
  * *Diagnosis:* Two separate custom `MachineConfig` objects targeting the same pool specify identical file paths with conflicting contents or file modes. The render controller cannot resolve the priority and halts rendering.
  * *Remediation Route:* **DO NOT edit the generated `rendered-*` object directly.** Route to **Manual CLI Fallback**:
    - Identify the two colliding source MachineConfigs.
    - Provide exact instructions to merge the configurations or adjust file ownership in GitOps / source repository.

* **Branch 3B: Node-Level Configuration Apply Failure (Host Filesystem / Systemd)**
  * *Evidence:* Target rendered MachineConfig exists, but MCD on the node marks `state: Degraded` with error: `error writing file /etc/...: no space left on device` or `permission denied` or `failed to reload systemd units: Process exited with status 1`.
  * *Diagnosis:* The rendered config is valid, but the target host cannot apply it due to local disk exhaustion on `/` or `/var`, an immutable filesystem attribute, or a broken systemd service unit definition.
  * *Remediation Route:* **Manual CLI Fallback (Host Diagnostics)**. Inspect host storage capacity and systemd journal logs.

* **Branch 3C: Unsupported Ignition Spec / Malformed MachineConfig Syntax**
  * *Evidence:* MCC logs report `cannot unmarshal Ignition specification` or `unsupported Ignition version 3.4.0 (max supported: 3.2.0)`.
  * *Diagnosis:* A newly applied MachineConfig was generated using an incompatible Ignition API version or contains malformed JSON/YAML payloads.
  * *Remediation Route:* **Manual CLI Fallback (MachineConfig Schema Correction)**.

---

## 4. Remediation Resolution Rules

### Absolute Safety Rule on Rendered MachineConfigs
> [!CAUTION]
> The diagnostic agent MUST NEVER attempt to directly edit, patch, or delete generated `rendered-<pool>-<hash>` objects (`oc edit mc rendered-worker-...`). Rendered MachineConfigs are strictly generated artifacts managed by MCC; modifying them directly causes state divergence, etcd thrashing, and immediate overwrite by the render controller. Edits MUST be applied to the underlying *source* `MachineConfig` objects.

### Rule 1: Manual CLI Fallback Generation (Branch 3A - Render Conflict)
**Triggered when:** Multiple custom MachineConfigs conflict on a shared file path.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "MachineConfig render conflict detected; multiple source configs define the same file path.",
  "manual_cli_fallback": {
    "risk_level": "medium",
    "pre_checks": [
      "# 1. Inspect MCP RenderDegraded condition message:",
      "oc get mcp {{ pool_name }} -o jsonpath='{.status.conditions[?(@.type==\"RenderDegraded\")].message}{\"\\n\"}'",
      "# 2. Locate the two colliding source MachineConfigs:",
      "oc get mc -l machineconfiguration.openshift.io/role={{ pool_name }} -o json | jq -r '.items[] | select(.spec.config.storage.files[]?.path==\"{{ conflicting_filepath }}\") | .metadata.name'"
    ],
    "remediation_steps": [
      "# 3. Review contents of the conflicting source configs:",
      "oc get mc {{ mc_a }} -o yaml",
      "oc get mc {{ mc_b }} -o yaml",
      "# 4. Consolidate file definitions into a single authoritative MachineConfig in your GitOps repository.",
      "# 5. Delete or update the redundant MachineConfig to clear the conflict:",
      "oc delete mc {{ mc_b }}"
    ],
    "safety_warning": "Always make MachineConfig modifications in version-controlled GitOps repositories before deleting live cluster objects.",
    "verification": [
      "oc get mcp {{ pool_name }} -o jsonpath='{.status.conditions[?(@.type==\"RenderDegraded\")].status}{\"\\n\"}{.status.configuration.name}{\"\\n\"}'"
    ]
  }
}
```

---

### Rule 2: Manual CLI Fallback Generation (Branch 3B - Node Apply / Disk Failure)
**Triggered when:** MCD fails to apply valid rendered config on the node.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "MCD failed to write configuration on host; local disk exhaustion or systemd failure suspected.",
  "manual_cli_fallback": {
    "risk_level": "high",
    "pre_checks": [
      "# 1. Inspect MCD pod logs on the failing node:",
      "oc -n openshift-machine-config-operator logs -l k8s-app=machine-config-daemon --field-selector spec.nodeName={{ node_name }} -c machine-config-daemon --tail=50",
      "# 2. Check disk space and mount states on the host:",
      "oc debug node/{{ node_name }} -- chroot /host df -h / /var /etc"
    ],
    "remediation_steps": [
      "# 3. If disk space is exhausted, clean up old container images or journals:",
      "oc debug node/{{ node_name }} -- chroot /host journalctl --vacuum-size=500M",
      "# 4. If systemd unit reload failed, inspect journalctl for the failing service:",
      "oc debug node/{{ node_name }} -- chroot /host systemctl status {{ failed_service }}",
      "# 5. Once host issue is cleared, trigger MCD retry by restarting MCD pod:",
      "oc -n openshift-machine-config-operator delete pod -l k8s-app=machine-config-daemon --field-selector spec.nodeName={{ node_name }}"
    ],
    "safety_warning": "Do not delete active system files to free space; only vacuum rotated journals or remove dangling container storage.",
    "verification": [
      "oc get node {{ node_name }} -o jsonpath='{.metadata.annotations.machineconfiguration\\.openshift\\.io/state}'"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Telemetry Ingestion Failure:** Splunk multi-index query fails or returns HTTP 5xx. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Transient Generation Delay:** New MachineConfig was created 10 seconds ago, and MCC is actively rendering. Report: `inconclusive: render_in_progress`.
3. **Missing MachineConfig Definition:** MCD reports apply error referencing a rendered config that does not exist in cluster inventory. Report: `inconclusive: rendered_config_object_missing`.
4. **Node Not Drained Yet:** MCD apply error logged, but node is still actively evicting pods (`spec.unschedulable: false`). Report: `not_supported: drain_not_completed_route_to_workload_skill`.

---

## 6. Post-Remediation Verification Contract

Whether executed via GitOps merge or host space recovery, recovery MUST be proven using these exact signals:

1. **RenderDegraded Cleared:** `mcp.status.conditions[?(@.type=="RenderDegraded")].status == "False"`.
2. **Target Rendered Config Bound:** `mcp.status.configuration.name == mcp.spec.configuration.name`.
3. **Node Apply Success:** Node annotation `machineconfiguration.openshift.io/state` transitions from `Working` to `Done`, and `currentConfig` equals `desiredConfig`.
