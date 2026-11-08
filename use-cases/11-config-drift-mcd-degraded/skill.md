---
skill_id: 11-config-drift-mcd-degraded
skill_version: 2.0.0
title: Fail-Proof Diagnosis for Machine Config Daemon Configuration Drift
lifecycle_stages:
- drain
- mcp_update
trigger_signatures:
- pattern: 11-config-drift-mcd-degraded
  source: ocp_logs
- pattern: Degraded
  source: ocp_logs
- pattern: 'inconclusive: lifecycle_stage_not_degraded'
  source: ocp_logs
supported_environments:
  openshift_versions:
  - 4.12+
  - 4.16+
  - 4.22+
  - '5.0'
  mco_versions:
  - 4.12+
  components:
  - name: machine-config-controller
  - name: machine-config-daemon
  - name: kubelet
  - name: kube-apiserver
  - name: openshift-virtualization
  - name: csi-driver
required_evidence:
- dataset: ocp_logs
  kinds: &id001
  - Node
  - MachineConfigPool
  - MachineConfig
  - Event
  max_age_seconds: 3600
- dataset: k8s_objects
  kinds: *id001
  max_age_seconds: 300
- dataset: prometheus
  metrics:
  - declared_by_skill_and_observability_matrix
  max_age_seconds: 300
freshness_limits_seconds:
  node_and_lease: 120
  pod_pdb_storage: 300
  mcp_and_operator: 600
decision_tree_version: 1.0.0
prohibited_actions:
- direct Kubernetes mutation
- force deletion
- unreviewed finalizer removal
- unapproved AAP execution
remediation_catalog_refs: []
evaluation_fixtures:
  negative: tests/fixtures/11-config-drift-mcd-degraded/negative_dossier.json
  contradictory: tests/fixtures/11-config-drift-mcd-degraded/contradictory_dossier.json
owner: platform-sre
status: draft
---

# Skill: Fail-Proof Diagnosis for Machine Config Daemon Configuration Drift (`11-config-drift-mcd-degraded`)

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
| **Lifecycle Stage** | Node or MCP is reporting `Degraded` state during preflight or update. | Exit: `inconclusive: lifecycle_stage_not_degraded` |
| **Trigger Signal** | Node annotation `machineconfiguration.openshift.io/state` is `Degraded` OR MCD pod logs in `index=ocp_logs` match: `(?i)(content of file.*does not match expected|unexpected file mode|config drift detected|node.*degraded.*drift|inconsistent.*on-disk)` OR Prometheus metric `machine_config_daemon_state{state="Degraded"} == 1`. | Exit: `not_supported: no_mcd_drift_logged` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Extract Drifted Node & Path]         [No MCD Drift Logged]
            Node name, drifted path, state/reason         ──► Exit: not_supported
                         │
                         ▼
            [Step 2: Differentiate Drift Target]
            Identify drifted object: Systemd unit, file, or ostree
                         │
         ┌───────────────┼───────────────────────────────┐
         ▼               ▼                               ▼
  [Allowlisted Service]  [Managed File Drift]            [Immutable /usr / OSTree]
  chronyd / crio daemon  /etc/* file content or          /usr/lib or filesystem
  unit failed/drifted    permissions modified            corruption detected
         │                       │                               │
         ▼                       ▼                               ▼
  Branch 3A: Unit        Branch 3B: Host File Drift      Branch 3C: OS Corruption
  Restart Playbook       (Manual CLI Diff & Forcefile)   (Manual CLI Re-image)
```

### Step 1: Extract Drifted Node & File Path
1. In `k8s_objects` / KV Store, inspect the target `Node` object:
   * Record annotation `machineconfiguration.openshift.io/state` (must be `Degraded`).
   * Record annotation `machineconfiguration.openshift.io/reason`.
   * Record `machineconfiguration.openshift.io/currentConfig` and `desiredConfig`.
2. Extract the exact drifted target from MCD logs in `index=ocp_logs`:
   ```regex
   (?i)content of file "(?<drifted_filepath>[^"]+)" does not match expected
   ```
   OR
   ```regex
   (?i)unexpected file mode for "(?<drifted_filepath>[^"]+)": expected (?<expected_mode>\d+), got (?<actual_mode>\d+)
   ```

### Step 2: Differentiate Host Service vs. Managed File vs. CoreOS Layer
1. **Case 2A: Drifted target is an allowlisted systemd unit:**
   * If error involves a crashed or deadlocked service unit (e.g. `chronyd.service`, `crio.service`): proceed to **Branch 3A**.
2. **Case 2B: Drifted target is a managed file in `/etc`:**
   * If error references an MCO-managed configuration file (e.g. `/etc/chrony.conf`, `/etc/sysctl.d/*`, `/etc/security/*`, `/etc/containers/registries.conf`): proceed to **Branch 3B**.
3. **Case 2C: Drifted target is in `/usr` or immutable ostree rootfs:**
   * If error references read-only filesystem or `/usr`: proceed to **Branch 3C**.

---

## 3. Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                              [MCD Configuration Drift]
                                          │
            ┌─────────────────────────────┼─────────────────────────────┐
            ▼                             ▼                             ▼
  [Branch 3A: Systemd Unit]     [Branch 3B: Managed File Drift] [Branch 3C: CoreOS Rootfs]
  Auxiliary service failed;     Manual edit / unmanaged agent   OSTree mismatch or corrupt
  node marked Degraded          altered /etc/* on live host     RHCOS filesystem
            │                             │                             │
            ▼                             ▼                             ▼
  Playbook: restart_systemd_    Playbook: null (Data Risk)      Playbook: null (OS Panic)
  unit (extra_vars: service)    CLI Fallback: Forcefile Diff    CLI Fallback: Node Re-image
```

* **Branch 3A: Recoverable Systemd Unit / Service Degradation**
  * *Evidence:* MCD marks node `Degraded` because an enabled systemd unit failed during verification (e.g. `chronyd.service`), but on-disk files match.
  * *Diagnosis:* Auxiliary host service crashed or failed restart during MCO preflight.
  * *Remediation Route:* **Clean Playbook Match $\rightarrow$ `playbook_restart_failed_systemd_unit`** with `systemd_service_name: "<unit>"`.

* **Branch 3B: Out-of-Band Administrative or Agent File Mutation**
  * *Evidence:* MCD logs report exact file mismatch: `content of file /etc/... does not match expected`.
  * *Diagnosis:* A human administrator, non-Kubernetes configuration management tool (Puppet/Chef/Ansible), or security agent modified an MCO-managed file directly on the host, causing MCD to refuse applying further MachineConfigs.
  * *Remediation Route:* **DO NOT touch host files autonomously.** Route to **Manual CLI Fallback**:
    - Compares current host content against the authoritative `MachineConfig` object.
    - Generates human-approved runbook to revert manual edits or create `/run/machine-config-daemon-force` to force MCO overwrite.

* **Branch 3C: CoreOS / Immutable OSTree Image Corruption**
  * *Evidence:* MCD logs report `read-only file system` or `/usr/lib` checksum mismatch.
  * *Diagnosis:* Underlying operating system storage corruption or unauthorized attempt to modify immutable RHCOS partitions.
  * *Remediation Route:* **CRITICAL SAFETY HALT $\rightarrow$ Manual CLI Fallback Only.** Node re-provisioning or hardware replacement required.

---

## 4. Remediation Resolution Rules

### Rule 1: Automated Playbook Match (`playbook_restart_failed_systemd_unit`)
**Conditions for Match:**
1. Branch 3A is satisfied (failed allowlisted systemd unit).
2. Node condition `Ready` is `True` (host networking alive).
3. Service is strictly in the allowlist (`chronyd`, `crio`, `systemd-journald`).

**Generated Output Spec:**
```json
{
  "matched": true,
  "playbook_id": "playbook_restart_failed_systemd_unit",
  "playbook_file": "playbooks/remediate-restart-systemd-unit.yml",
  "risk_level": "medium",
  "requires_approval": true,
  "aap_extra_vars": {
    "target_cluster": "{{ cluster_id }}",
    "target_node": "{{ node_name }}",
    "systemd_service_name": "{{ failed_service }}"
  },
  "verification_goal": "mcd_degraded == false and node_state == 'Done'"
}
```

---

### Rule 2: Manual CLI Fallback Generation (Branch 3B - Managed File Drift)
**Triggered when:** On-disk file in `/etc` was modified out-of-band.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Host file drift detected; human approval required to overwrite local changes with authoritative MachineConfig.",
  "manual_cli_fallback": {
    "risk_level": "high",
    "pre_checks": [
      "# 1. Inspect exact drift reason on the degraded node:",
      "oc get node {{ node_name }} -o jsonpath='State: {.metadata.annotations.machineconfiguration\\.openshift\\.io/state}{\"\\n\"}Reason: {.metadata.annotations.machineconfiguration\\.openshift\\.io/reason}{\"\\n\"}'",
      "# 2. Inspect drifted file content directly on the host:",
      "oc debug node/{{ node_name }} -- chroot /host cat {{ drifted_filepath }}"
    ],
    "remediation_steps": [
      "# 3. Compare with authoritative content in the rendered MachineConfig:",
      "oc get mc {{ desired_config_name }} -o json | jq '.spec.config.storage.files[] | select(.path==\"{{ drifted_filepath }}\")'",
      "# 4. Option A (Revert manual change): Edit file back to expected content or permissions on host.",
      "# 5. Option B (Force MCO overwrite): Trigger MCO force-reapply by creating forcefile:",
      "oc debug node/{{ node_name }} -- chroot /host touch /run/machine-config-daemon-force"
    ],
    "safety_warning": "Touching /run/machine-config-daemon-force instructs MCD to overwrite all local changes and may immediately reboot the node.",
    "verification": [
      "oc get node {{ node_name }} -o jsonpath='{.metadata.annotations.machineconfiguration\\.openshift\\.io/state}'",
      "oc get mcp {{ pool_name }} -o jsonpath='{.status.conditions[?(@.type==\"Degraded\")].status}'"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Telemetry Ingestion Failure:** Splunk multi-index query fails or returns HTTP 5xx. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Normal Rollout Ambiguity:** Node `currentConfig != desiredConfig`, but annotation `state == "Working"` (update actively applying, not drifted). Report: `not_supported: node_actively_applying_update`.
3. **Missing Node Record:** Degraded node is not found in KV Store. Report: `inconclusive: node_record_missing`.
4. **Unidentifiable Drift File:** MCD reports drift but does not specify a valid file path in logs or annotations. Report: `inconclusive: drift_target_unidentified`.

---

## 6. Post-Remediation Verification Contract

Whether executed via AAP playbook or manual CLI, recovery MUST be proven using these exact signals:

1. **Node State Cleared:** `node.metadata.annotations['machineconfiguration.openshift.io/state'] == "Done"`.
2. **MCP Degraded Cleared:** `mcp.status.conditions[?(@.type=="Degraded")].status == "False"`.
3. **MCD Preflight Passing:** MCD logs in `index=ocp_logs` confirm verification pass without on-disk mismatch warnings.
## Service allowlist clarification (2026-11-08)

Only service names declared in the catalog are eligible for the service-restart recommendation, and each uses its service-specific risk profile. A failed auxiliary service such as `chronyd` is not equivalent to restarting `crio`, `kubelet` or `systemd-journald`; the latter require high-risk human approval and their own preconditions. File drift, immutable OS corruption and ambiguous MCD degradation never match a service-restart playbook.
