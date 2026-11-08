# Ansible Remediation Catalog & Two-Tier Execution Model

This directory defines the **Remediation Catalog** for the MCO Drain Troubleshooting Agent. 

The agent operates in a **strictly read-only diagnostic mode**. It does not mutate OpenShift clusters directly. 

---

## Phased Remediation Strategy (Day-1 vs Final Phase)

To eliminate infrastructure friction during initial development and deployment, remediation follows a two-phase rollout:

* **Day-1 Phase (Diagnostic & Pseudo-Code Mode):**
  - The agent evaluates diagnosed root causes against [`PLAYBOOK_CATALOG.json`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/remediations/PLAYBOOK_CATALOG.json).
  - It outputs **Ansible Playbook Pseudo-Code** (formatted YAML task definitions with variables populated) for human SRE review.
  - It outputs **Copy-Pasteable Manual `oc` CLI Runbooks** for immediate SRE resolution.
  - **Zero Ansible infrastructure is required on Day 1.** No AWX/AAP tokens, execution environments, or playbook files needed.
* **Final Phase (Automated AAP Integration):**
  - Tested production `.yml` playbooks are stored in the corporate Git repository.
  - The agent’s output payload triggers the Ansible Automation Platform (AAP / AWX) Job Launch API with verified `extra_vars`.

---

## Day-1 Diagnostic Output Architecture

```
                     [Diagnostic Agent Output]
                                 │
                   ┌─────────────┴─────────────┐
                   ▼                           ▼
          [Playbook Match]            [No Playbook Match]
         Standard Tested Fix         Complex / High-Risk
                   │                           │
                   ▼                           ▼
      [Ansible YAML Pseudo-Code]     [Manual CLI Runbook]
      • Formatted YAML tasks         • Exact 'oc' commands
      • Populated variables          • Pre-checks & warnings
      • Verification assertions      • Rollback instructions
```

---

## Approved Remediation Pseudo-Code Catalog

The catalog defines 6 approved automated remediations:

1. **`playbook_pdb_scale_up`** ([`01-pdb-eviction-blocked`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/use-cases/01-pdb-eviction-blocked)): Temporarily scales up a deployment replica count by +1 using `kubernetes.core.k8s_scale` to satisfy PDB `minAvailable` constraints during drain.
2. **`playbook_restart_csi_driver`** ([`04-storage-unmount-detach`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/use-cases/04-storage-unmount-detach)): Deletes a hung CSI node-driver daemon pod on the draining node via `kubernetes.core.k8s` to force Kubelet restart.
3. **`playbook_reconcile_drain_annotation`** ([`14-uncordon-or-drainer-annotation`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/use-cases/14-uncordon-or-drainer-annotation)): Restores MCO drain coordination annotations on the Node object after an external uncordon race condition.
4. **`playbook_unpause_mcp`** ([`10-mcp-paused-or-coordination`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/use-cases/10-mcp-paused-or-coordination)): Unpauses a healthy, non-degraded MachineConfigPool.
5. **`playbook_cleanup_stale_virt_launcher`** ([`06-ocv-stale-virt-launcher`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/use-cases/06-ocv-stale-virt-launcher)): Removes an orphaned virt-launcher pod from the source node after verifying the VM has successfully live-migrated to another host.
6. **`playbook_restart_failed_systemd_unit`** ([`08-node-kubelet-crio-unreachable`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/use-cases/08-node-kubelet-crio-unreachable), [`11-config-drift-mcd-degraded`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/use-cases/11-config-drift-mcd-degraded)): Restarts an allowlisted host systemd service via `ansible.builtin.systemd`.

---

## When No Playbook Matches (Guarded Manual CLI Fallback)

If an incident does not match any approved catalog entry (or involves dangerous actions like clearing finalizers or force-deleting pods), the agent outputs a `manual_cli_fallback` payload:
* **Target Context:** Specific cluster, node, namespace, and resource names.
* **Pre-Checks:** Verification commands to confirm the issue before taking action.
* **Exact Command:** The safe, scoped `oc` command to execute.
* **Safety Warnings & Rollback Plan:** Explicit risks and rollback instructions.
* **Post-Verification:** Command to prove the drain progressed.
