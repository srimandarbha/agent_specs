# Reason Codes Registry & Stop Semantics

## 1. Overview & Policy

Every diagnostic outcome that halts or completes without matching an automated remediation playbook must emit a **canonical reason code** from this registry. 

### Core State Invariants
1. **`inconclusive`**: Telemetry is missing, stale, contradictory, wrong-cluster, or backend adapters failed. Remediation is **strictly prohibited** (`remediation_kind: none`, `playbook_match: false`, `playbook_id: null`).
2. **`not_supported`**: The investigated condition is either normal operational behavior, historical/cleared, or outside the automated scope. No automated remediation is permitted (`remediation_kind: none`).
3. **`probable`**: High likelihood root cause identified, but mandatory verification signals are incomplete or secondary indicators require human SRE judgment. Only guarded manual CLI runbooks with explicit pre-checks are permitted.
4. **`supported` (with halt/handoff)**: A specific fault or interlock is proven, but requires cross-skill handoff or human operational sign-off rather than an automated playbook.

---

## 2. Alias Reconciliations & Normalizations

To eliminate intra-file and cross-skill discrepancies (such as UC01 §2 using `overlapping_pdb_configuration` while §5 uses `multiple_overlapping_pdbs_detected`), runtime loaders and decision engines must normalize all legacy or draft strings to their canonical code:

| Raw / Draft String in Skill | Canonical Reason Code | Status | Remediation Allowed |
|---|---|---|---|
| `overlapping_pdb_configuration` | `multiple_overlapping_pdbs_detected` | `inconclusive` | No |
| `drain_not_completed_route_to_workload_skill` | `drain_in_progress_route_to_workload_skill` | `supported` | No (Handoff) |
| `transient_migration_network_timeout` | `transient_network_timeout` | `inconclusive` | No |
| `node_pressure_cleared` | `no_node_resource_pressure_detected` | `not_supported` | No |
| `stale_snapshot` | `pdb_state_stale` / `stale_telemetry` | `inconclusive` | No |

---

## 3. Authoritative Reason Code Catalog

### 3.1 Infrastructure, Adapter & Telemetry Quality Codes

| Reason Code | Canonical Status | Permitted Remediation | Description & Failure Semantics | Applicable Use Cases |
|---|---|---|---|---|
| `invalid_cluster_context` | `inconclusive` | `none` | Target `cluster_id` is unknown, unauthorized, or missing from cluster registry. | All (Entry Gate) |
| `telemetry_backend_unavailable` | `inconclusive` | `none` | Splunk or Prometheus MCP query timed out or returned HTTP 5xx after 1 retry. | All |
| `wrong_cluster_evidence` | `inconclusive` | `none` | Ingested evidence contains telemetry belonging to a cluster other than the target. | All |
| `no_evidence` | `inconclusive` | `none` | Adapter returned 0 records for a mandatory target query. | All |
| `pdb_state_stale` | `inconclusive` | `none` | PDB/Pod snapshot exceeds active-incident freshness limit (300s). | UC01 |
| `stale_telemetry` | `inconclusive` | `none` | Telemetry age exceeds observability matrix freshness limits without recent events. | All |
| `contradictory_telemetry` | `inconclusive` | `none` | Conflicting signals (e.g. eviction 429 logged but `disruptionsAllowed > 0`). | UC01, UC02, UC06, UC11, UC16 |
| `transient_network_timeout` | `inconclusive` | `none` | Isolated single network blip without persistent controller degradation. | UC02, UC05, UC08, UC09 |

### 3.2 Lifecycle Stage Mismatch Codes

| Reason Code | Canonical Status | Permitted Remediation | Description & Failure Semantics | Applicable Use Cases |
|---|---|---|---|---|
| `lifecycle_stage_not_drain` | `inconclusive` | `none` | Node is not cordoned or MCO is not in drain phase. | UC01, UC03, UC04, UC06, UC07, UC16 |
| `lifecycle_stage_not_apply` | `inconclusive` | `none` | MCD is not in config apply stage. | UC11, UC12 |
| `lifecycle_stage_not_pivot_reboot` | `inconclusive` | `none` | Node is not in OS pivot or rebooting stage. | UC13 |
| `lifecycle_stage_not_degraded` | `inconclusive` | `none` | MachineConfigPool is not reporting Degraded condition. | UC10, UC11 |
| `lifecycle_stage_not_node_maintenance` | `inconclusive` | `none` | Target node is not marked for drain or maintenance. | UC14, UC15 |
| `lifecycle_stage_not_drain_or_migration` | `inconclusive` | `none` | Node is neither draining nor hosting migrating VirtualMachineInstances. | UC05 |
| `lifecycle_stage_not_updating` | `inconclusive` | `none` | MachineConfigPool is not in updating phase. | UC10, UC12 |

### 3.3 Non-Fault & Normal Operation Codes (Negative Tests)

| Reason Code | Canonical Status | Permitted Remediation | Description & Failure Semantics | Applicable Use Cases |
|---|---|---|---|---|
| `no_pdb_eviction_denial_logged` | `not_supported` | `none` | No eviction denial matching PDB regex in MCC logs. | UC01 |
| `pdb_disruptions_allowed_positive` | `not_supported` | `none` | PDB `disruptionsAllowed > 0`; eviction is not blocked by PDB quota. | UC01 |
| `no_webhook_admission_error_logged` | `not_supported` | `none` | No admission webhook timeout or denial in API audit/logs. | UC02 |
| `webhook_already_removed` | `not_supported` | `none` | Failing webhook configuration object has already been deleted. | UC02 |
| `no_pod_termination_error_logged` | `not_supported` | `none` | Pod terminated cleanly within standard grace period. | UC03 |
| `pod_already_terminated` | `not_supported` | `none` | Target pod no longer exists in etcd / object cache. | UC03 |
| `pod_not_in_terminating_state` | `not_supported` | `none` | Pod has no `deletionTimestamp`; termination not initiated. | UC03 |
| `no_storage_unmount_error_logged` | `not_supported` | `none` | Volumes detached cleanly without mount error. | UC04 |
| `no_vmi_migration_block_logged` | `not_supported` | `none` | VirtualMachineInstance migration succeeded or was never scheduled. | UC05 |
| `vm_already_stopped` | `not_supported` | `none` | Target VM is powered down / stopped. | UC05 |
| `no_virt_launcher_drain_error_logged` | `not_supported` | `none` | virt-launcher pod evicted without stall. | UC06 |
| `no_failed_scheduling_events_logged` | `not_supported` | `none` | Replacement pods scheduled without capacity/affinity errors. | UC07 |
| `pod_scheduled_successfully` | `not_supported` | `none` | Target pod transitioned from Pending to Running. | UC07 |
| `node_is_ready_and_responsive` | `not_supported` | `none` | Kubelet and CRI-O responding to lease/probes; Node Ready=True. | UC08 |
| `control_plane_latency_within_thresholds` | `not_supported` | `none` | API server and etcd p99 latency < 500ms; no degradation. | UC09 |
| `no_drain_coordination_error_logged` | `not_supported` | `none` | Node drain coordination advancing normally. | UC10 |
| `pool_is_not_paused` | `not_supported` | `none` | MachineConfigPool `spec.paused` is false and no pause annotation exists. | UC10 |
| `pool_rollout_in_progress_respecting_concurrency_limits` | `not_supported` | `none` | MCP rollout progressing within `maxUnavailable` budget. | UC10 |
| `no_mcd_drift_logged` | `not_supported` | `none` | Machine Config Daemon verifies on-disk state matches rendered MC. | UC11 |
| `no_render_or_apply_error_logged` | `not_supported` | `none` | Ignition/MachineConfig applied without error. | UC12 |
| `no_os_pivot_or_reboot_error_logged` | `not_supported` | `none` | rpm-ostree pivot and systemd reboot completed within SLA. | UC13 |
| `host_reboot_in_progress_within_grace_window` | `not_supported` | `none` | Node currently rebooting within expected 15-minute maintenance window. | UC13 |
| `no_node_resource_pressure_detected` | `not_supported` | `none` | Disk, memory, and PID pressure conditions are all False. | UC15 |
| `no_max_volume_count_events_logged` | `not_supported` | `none` | AttachVolume limit not exceeded on target node. | UC16 |

### 3.4 Missing Telemetry & Inventory Inconsistency Codes

| Reason Code | Canonical Status | Permitted Remediation | Description & Failure Semantics | Applicable Use Cases |
|---|---|---|---|---|
| `pdb_deleted_or_selector_mismatch` | `probable` | `manual_cli` | Eviction failed citing PDB, but 0 PDBs select target pod labels. | UC01 |
| `pdb_record_missing_from_cache` | `probable` | `manual_cli` | PDB object not found in telemetry store despite MCC log citation. | UC01 |
| `rendered_config_object_missing` | `inconclusive` | `none` | Desired rendered MachineConfig missing from `k8s_objects`. | UC12 |
| `mcp_record_missing` | `inconclusive` | `none` | MachineConfigPool resource missing from inventory cache. | UC10 |
| `node_record_missing` | `inconclusive` | `none` | Target Node resource missing from inventory cache. | UC11, UC15 |
| `volume_attachment_record_missing` | `inconclusive` | `none` | VolumeAttachment object absent during detach failure diagnosis. | UC04 |
| `virt_launcher_pod_missing` | `inconclusive` | `none` | virt-launcher pod not located in namespace. | UC06 |
| `drift_target_unidentified` | `inconclusive` | `none` | MCD reports drift but specific corrupted file/unit not reported. | UC11 |

### 3.5 Ambiguity & Policy Interlock Codes

| Reason Code | Canonical Status | Permitted Remediation | Description & Failure Semantics | Applicable Use Cases |
|---|---|---|---|---|
| `multiple_overlapping_pdbs_detected` | `inconclusive` | `none` | Pod labels match >=2 overlapping PDBs. Eviction returns HTTP 500. | UC01 |
| `multi_owner_finalizers_detected` | `inconclusive` | `none` | Pod contains multiple third-party finalizers requiring separate manual triage. | UC03 |
| `all_nodes_cordoned_cluster_wide_maintenance` | `inconclusive` | `none` | All schedulable nodes are cordoned; cluster-wide outage or maintenance. | UC07 |
| `cluster_wide_apiserver_degradation_detected` | `inconclusive` | `none` | Latency spike affects all API instances; systemic control plane issue. | UC09 |
| `pool_contains_unready_nodes` | `inconclusive` | `none` | Unready nodes in MCP prevent advancing rollout. | UC10 |
| `unsupported_drain_annotation_schema` | `inconclusive` | `none` | Node drain annotation does not conform to MCO JSON format. | UC14 |
| `no_branch_matched` | `inconclusive` | `none` | Fallback when evidence matches entry gate but no specific sub-branch triggers. | All |

### 3.6 Cross-Skill Routing & Handoff Codes

| Reason Code | Canonical Status | Permitted Remediation | Description & Failure Semantics | Applicable Use Cases |
|---|---|---|---|---|
| `drain_in_progress_route_to_workload_skill` | `supported` | `none` (Handoff) | Node drain is blocked by workload pod; route to UC01, UC03, or UC04. | UC14 |
| `node_network_partitioned_handoff_to_08` | `supported` | `none` (Handoff) | Unresponsiveness caused by host network loss; route to UC08. | UC02, UC03 |
| `vmi_migration_incomplete_route_to_05` | `supported` | `none` (Handoff) | virt-launcher termination waiting on VMI migration; route to UC05. | UC06 |
| `vm_still_homed_on_draining_node` | `supported` | `none` (Handoff) | Live migration failed to relocate VMI from draining host. | UC05 |
| `hardware_storage_controller_fault_requires_node_reprovisioning` | `supported` | `none` (Handoff) | Kernel reports hardware I/O lockup; node reprovisioning required. | UC04 |

---

## 4. Programmatic Verification Rule

In all evaluation fixtures, reference oracles, and production graph nodes:
```python
assert stop_reason in ALL_REGISTERED_REASON_CODES, f"Unregistered stop_reason: {stop_reason}"
if classification in ("inconclusive", "not_supported"):
    assert remediation_kind == "none", f"Remediation forbidden for {classification}"
if classification == "supported" and confidence == "high":
    assert stop_reason is None, "Supported/high finding cannot carry a stop_reason"
```
