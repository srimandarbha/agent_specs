# Skill: Fail-Proof Diagnosis for OS Pivot, Reboot or Post-Reboot Verification Failure (`13-os-pivot-reboot-failure`)

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
| **Lifecycle Stage** | MachineConfigPool is in `Updating` and target node is in pivot, reboot, or post-reboot verification phase. | Exit: `inconclusive: lifecycle_stage_not_pivot_reboot` |
| **Trigger Signal** | MCD logs in `index=ocp_logs` match: `(?i)(failed to pivot|rpm-ostree.*failed|reboot.*failed|booted deployment.*does not match|failed to verify booted|node has not rebooted)` OR Node condition `Ready` is `Unknown` past the expected reboot grace window (> 15m) OR Node annotation `state` is `Degraded` with reason `FailedToVerifyBootedDeployment`. | Exit: `not_supported: no_os_pivot_or_reboot_error_logged` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Ingest Node Pivot & Boot State]      [No Pivot/Reboot Error]
            Check Node annotations, lease age, MCD logs   ──► Exit: not_supported
                         │
                         ▼
            [Step 2: Differentiate Failure Phase]
            Evaluate pre-reboot pivot, reboot hang, or post-reboot verification
                         │
         ┌───────────────┼───────────────────────────────┐
         ▼               ▼                               ▼
  [Pre-Reboot Pivot]     [Host Reboot Hang]              [Post-Reboot Rollback]
  rpm-ostree failed      Node lease expired > 15m;       Node returned Ready, but
  staging new OS image   host silent; BIOS/kernel hang   booted into wrong deployment
         │                       │                               │
         ▼                       ▼                               ▼
  Branch 3A: OSTree      Branch 3B: Reboot Hang /        Branch 3C: Verification
  Staging / /boot Full   Console Deadlock                Mismatch / Auto-Rollback
```

### Step 1: Ingest Node Pivot & Boot State
1. In `k8s_objects` / KV Store, inspect the target `Node` object:
   * Record annotation `machineconfiguration.openshift.io/state` (e.g. `Working`, `Degraded`).
   * Record annotation `machineconfiguration.openshift.io/reason`.
   * Record `machineconfiguration.openshift.io/currentConfig` and `desiredConfig`.
   * Check `kube-node-lease` renew time:
     * If renew time is > 900s (15 minutes) stale: Proceed to **Branch 3B (Reboot Hang)**.
2. In `index=ocp_logs`, inspect MCD pod logs for the target node:
   * Filter for pivot commands: `rpm-ostree rebase`, `pivot.go`, `Writing pivot deployment`.
   * Filter for post-reboot checks: `Checking if node has rebooted`, `Verifying booted OS configuration`.

### Step 2: Differentiate Pre-Reboot Staging, Reboot Hang, and Post-Reboot Verification
1. **Case 2A: Pre-Reboot Staging Failure:**
   * Node is still running on the old kernel (has not rebooted yet).
   * MCD logs report error during image pull or `rpm-ostree` preparation:
     ```regex
     (?i)(failed to run rpm-ostree.*no space left on device|error pulling machine-os-content|failed to rebase)
     ```
   * Proceed to **Branch 3A**.
2. **Case 2B: Host Reboot Hang / Kernel Freeze:**
   * Node was cordoned and MCD issued reboot, but node has not rejoined cluster within 15 minutes.
   * `up{job="kubelet"} == 0` and `kube-node-lease` is stale > 15m.
   * Proceed to **Branch 3B**.
3. **Case 2C: Post-Reboot Verification Failure / Auto-Rollback:**
   * Node successfully rebooted and Kubelet is `Ready`, but MCD logs report:
     ```regex
     (?i)(booted ostree commit.*does not match desired|failed to verify booted deployment)
     ```
   * Proceed to **Branch 3C**.

---

## 3. Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                            [OS Pivot / Reboot Failure]
                                         │
            ┌────────────────────────────┼────────────────────────────┐
            ▼                            ▼                            ▼
  [Branch 3A: Pivot Staging]   [Branch 3B: Reboot Hang]     [Branch 3C: Post-Reboot Rollback]
  /boot space exhausted or     Host hung in firmware/GRUB   Watchdog or kernel crash caused
  machine-os-content pull fail or systemd unmount deadlock  RHCOS to boot old deployment
            │                            │                            │
            ▼                            ▼                            ▼
  Playbook: null (Disk/Net)    Playbook: null (Hardware)    Playbook: null (OS Kernel)
  CLI Fallback: Clean /boot    CLI Fallback: Console / IPMI CLI Fallback: Inspect OSTree
```

* **Branch 3A: Pre-Reboot Pivot Staging Failure (`/boot` Disk Full or Image Pull Error)**
  * *Evidence:* MCD logs show: `rpm-ostree rebase failed: fatal: Write to disk failed: No space left on device` or `failed to resolve machine-os-content image`.
  * *Diagnosis:* The host cannot stage the new RHCOS deployment because accumulated older kernels in `/boot` have exhausted disk space, or network/registry authentication fails for the os-content container.
  * *Remediation Route:* **Manual CLI Fallback (Host `/boot` Inspection & Cleanup)**.

* **Branch 3B: Host Reboot Hang / Firmware / Kernel Freeze**
  * *Evidence:* The node was issued `systemctl reboot`, but has remained completely silent for > 15 minutes. Prometheus metric `up{job="kubelet"} == 0`.
  * *Diagnosis:* Host is stuck in UEFI/BIOS firmware, GRUB bootloader hang, or a kernel panic occurred before Kubelet initialization.
  * *Remediation Route:* **CRITICAL SAFETY HALT $\rightarrow$ Manual CLI Fallback Only.**
  * *Strict Warning:* Never issue repeated automated reboots. Require human inspection of the out-of-band IPMI / virtual console.

* **Branch 3C: Post-Reboot Verification Failure / OSTree Automatic Rollback**
  * *Evidence:* Node rejoined the cluster (`Ready: True`), but MCD marks annotation `state: Degraded` with error: `booted deployment does not match desired rendered config`.
  * *Diagnosis:* Greenboot (the health check framework in RHCOS) detected a critical service crash on boot and automatically rolled back GRUB to the previous functional OS deployment.
  * *Remediation Route:* **Manual CLI Fallback (Greenboot / OSTree Diagnostics)**.

---

## 4. Remediation Resolution Rules

### Absolute Safety Rule on OS Pivots and Reboots
> [!CAUTION]
> The diagnostic agent MUST NEVER initiate autonomous reboots, node power cycling, or forced ostree deployments. An unresponsive node during an OS pivot may be in the middle of writing bootloader metadata to disk; an uncoordinated power cycle will corrupt the GRUB partition and brick the host operating system.

### Rule 1: Manual CLI Fallback Generation (Branch 3A - Pivot Staging / `/boot` Full)
**Triggered when:** `rpm-ostree` fails to stage the new deployment before reboot.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Pre-reboot OS staging failed; /boot space exhaustion or os-content image pull failure.",
  "manual_cli_fallback": {
    "risk_level": "medium",
    "pre_checks": [
      "# 1. Inspect MCD logs on the affected node:",
      "oc -n openshift-machine-config-operator logs -l k8s-app=machine-config-daemon --field-selector spec.nodeName={{ node_name }} -c machine-config-daemon --tail=50",
      "# 2. Inspect /boot filesystem utilization on the host:",
      "oc debug node/{{ node_name }} -- chroot /host df -h /boot"
    ],
    "remediation_steps": [
      "# 3. If /boot is near 100%, clean up obsolete staged ostree deployments:",
      "oc debug node/{{ node_name }} -- chroot /host rpm-ostree cleanup -m",
      "# 4. Check status of deployments:",
      "oc debug node/{{ node_name }} -- chroot /host rpm-ostree status",
      "# 5. Restart MCD pod to trigger clean re-attempt:",
      "oc -n openshift-machine-config-operator delete pod -l k8s-app=machine-config-daemon --field-selector spec.nodeName={{ node_name }}"
    ],
    "safety_warning": "Never manually delete files from /boot; always use 'rpm-ostree cleanup' to prune unreferenced deployments.",
    "verification": [
      "oc get node {{ node_name }} -o jsonpath='{.metadata.annotations.machineconfiguration\\.openshift\\.io/state}'"
    ]
  }
}
```

---

### Rule 2: Manual CLI Fallback Generation (Branch 3B - Host Reboot Hang)
**Triggered when:** Node fails to return within 15 minutes of reboot initiation.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Host did not return after reboot command; firmware, GRUB, or kernel freeze suspected.",
  "manual_cli_fallback": {
    "risk_level": "critical",
    "pre_checks": [
      "# 1. Verify lease timestamp and node conditions:",
      "oc get lease -n kube-node-lease {{ node_name }} -o yaml",
      "# 2. Connect to out-of-band IPMI / virtual console to view boot screen:",
      "ipmitool -H {{ bmc_ip }} -U {{ bmc_user }} sol activate"
    ],
    "remediation_steps": [
      "# 3. Observe the host console for GRUB error, kernel panic, or hung systemd service.",
      "# 4. If host is hung at BIOS/GRUB, issue power reset via BMC.",
      "# 5. If kernel panics on the new image, select previous deployment in GRUB menu to recover."
    ],
    "safety_warning": "Do not delete the Node object in Kubernetes while host is offline.",
    "verification": [
      "oc get node {{ node_name }} -o jsonpath='{.status.conditions[?(@.type==\"Ready\")].status}'"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Telemetry Ingestion Failure:** Splunk multi-index query fails or returns HTTP 5xx. Report: `inconclusive: telemetry_backend_unavailable`.
2. **Normal Reboot In-Flight:** Node reboot was initiated less than 8 minutes ago, and heartbeat is temporarily silent. This is **normal reboot progression**. Report: `not_supported: host_reboot_in_progress_within_grace_window`.
3. **Missing Node Record:** Target node specified in alert is not found in KV Store. Report: `inconclusive: node_record_missing`.
4. **Hardware Console Unavailable:** Remote IPMI / BMC credentials or console telemetry cannot be accessed. Prohibit automated recovery.

---

## 6. Post-Remediation Verification Contract

Whether executed via `/boot` cleanup or console recovery, recovery MUST be proven using these exact signals:

1. **Node Ready Restored:** `node.status.conditions[?(@.type=="Ready")].status == "True"`.
2. **Current Config Matches Desired:** `node.metadata.annotations['machineconfiguration.openshift.io/currentConfig'] == node.metadata.annotations['machineconfiguration.openshift.io/desiredConfig']`.
3. **Node State Done:** `node.metadata.annotations['machineconfiguration.openshift.io/state'] == "Done"`.
4. **MCO Pool Progression:** MachineConfigPool `updatedMachineCount` increments.
