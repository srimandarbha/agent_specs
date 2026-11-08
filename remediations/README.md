# Ansible Remediation Catalog & Two-Tier Execution Model

This directory defines the **Remediation Catalog** for the MCO Drain Troubleshooting Agent. 

The agent operates in a **read-only diagnostic mode**. It does not directly mutate OpenShift clusters. Instead, it evaluates diagnosed root causes against [`PLAYBOOK_CATALOG.json`](file:///home/sdarbha/Projects/mcp/mco-drain-troubleshooting-pack/remediations/PLAYBOOK_CATALOG.json) and outputs either an **Ansible Automation Platform (AAP / AWX) execution spec** or an exact **manual `oc` CLI fallback runbook**.

---

## The Two-Tier Execution Model

```
                     [Diagnostic Agent Output]
                                 │
                   ┌─────────────┴─────────────┐
                   ▼                           ▼
          [Playbook Match]            [No Playbook Match]
         Clean, tested fix           Complex / High-Risk
                   │                           │
                   ▼                           ▼
         [AAP Job Spec]              [Manual CLI Runbook]
         • Playbook ID               • Exact 'oc' commands
         • Validated extra_vars      • Pre-checks & warnings
         • Verification goal         • Rollback instructions
```

---

## Catalog Playbooks Summary

1. **`playbook_pdb_scale_up`** (Use Case 01): Temporarily scales up a deployment replica to satisfy PDB `minAvailable` constraints during drain.
2. **`playbook_restart_csi_driver`** (Use Case 04): Restarts a hung CSI node-driver daemon pod on the draining node to clear storage detach deadlocks.
3. **`playbook_reconcile_drain_annotation`** (Use Case 14): Restores MCO drain coordination annotations after an external uncordon race condition.
4. **`playbook_unpause_mcp`** (Use Case 10): Safely unpauses a paused MachineConfigPool.
5. **`playbook_cleanup_stale_virt_launcher`** (Use Case 06): Deletes an orphaned virt-launcher pod on the source node once the VM is confirmed healthy on the destination node.
6. **`playbook_restart_failed_systemd_unit`** (Use Cases 08, 11): Restarts a non-critical failed systemd service that caused an MCD degraded condition.

---

## When No Playbook Matches (Intelligent CLI Fallback)

If an incident does not match any approved playbook (or involves dangerous actions like clearing finalizers or force-deleting pods), the agent **must not invent a playbook**. 

Instead, it outputs a `manual_cli_fallback` payload:
* **Target Context:** Specific cluster, node, namespace, and resource names.
* **Pre-Checks:** Verification commands to confirm the issue.
* **Exact Command:** The safe, scoped `oc` command to execute.
* **Safety Warnings & Rollback Plan:** Instructions on how to revert if the command fails.
* **Post-Verification:** Command to prove the drain progressed.
