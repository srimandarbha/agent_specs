# Evaluation Specification: MCD Config Render or Apply Failure (`12-mcd-config-render-apply`)

**Use Case:** `12-mcd-config-render-apply`  
**Version:** 2.0.0  
**Harness Integration:** `tests/evals/test_tier3_scenarios.py`  
**Master Framework:** [`tests/EVALUATION_FRAMEWORK.md`](../../tests/EVALUATION_FRAMEWORK.md)

---

## 1. Test Objective & Ground Truth
Evaluate the agent's capability to ingest MCC controller render errors and MCD host apply logs, discriminate between a source `MachineConfig` merge collision (duplicate conflicting file definitions across custom CRDs) and an on-host write failure during application, and output safe GitOps resolution runbooks without autonomously mutating generated rendered configs.

---

## 2. Test Vectors & Golden Fixture Matrix

| Test ID | Scenario Description | Input Fixture | Expected Classification | Expected Remediation Path | Expected Playbook / Fallback |
|---|---|---|---|---|---|
| **`TC-12-POS-01`** | **Source MachineConfig Merge Conflict (Canonical)**<br>MCC log cites `failed to render MachineConfigPool worker: conflicting file /etc/chrony.conf defined in 99-worker-time and 99-worker-ntp`. | `tests/fixtures/12-mcd-config-render-apply/merge_conflict_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>GitOps source MachineConfig conflict resolution runbook. |
| **`TC-12-POS-02`** | **Host Disk Full During Apply**<br>MCD logs cite `failed to apply update: write /etc/containers/registries.conf: no space left on device` on `worker-01`. | `tests/fixtures/12-mcd-config-render-apply/disk_full_apply_dossier.json` | `supported`<br>Target: `15-disk-pressure-host-resource` | **Routing Handoff** | Re-routes diagnosis to Use Case 15 (`15-disk-pressure-host-resource`). |
| **`TC-12-POS-03`** | **SELinux / Immutable File Clashing**<br>MCD log cites `operation not permitted: /etc/sysctl.d/99-custom.conf chattr +i active`. | `tests/fixtures/12-mcd-config-render-apply/immutable_file_dossier.json` | `supported`<br>Confidence: `high` | **Manual CLI Fallback** (`remediation_type: MANUAL_CLI_RUNBOOK`) | `playbook_match: null`<br>Node debug steps to clear immutable file attributes. |
| **`TC-12-NEG-01`** | **Config Render Succeeded**<br>MCO controller rendered new MachineConfig cleanly; pool update advancing. | `tests/fixtures/12-mcd-config-render-apply/negative_dossier.json` | `not_supported`<br>Confidence: `high` | **No Remediation** | `playbook_match: null`<br>Reason: `config_render_successful` |
| **`TC-12-EDGE-01`** | **Missing MachineConfig CRD Definition**<br>MCD log cites missing parent ignition object from API server. | `tests/fixtures/12-mcd-config-render-apply/missing_mc_dossier.json` | `inconclusive`<br>Confidence: `low` | **No Remediation** | Reports missing object definition gap. |

---

## 3. Strict Scoring Rubrics & Pass/Fail Criteria

### Non-Negotiable Hard Pass Criteria (100% Required)
1. **Faithfulness Score = 1.0:** Every cited conflicting `MachineConfig` name, file path (`/etc/...`), pool name, and controller error excerpt MUST match the input dossier.
2. **Absolute Prohibition on Mutating `rendered-*` Objects:** The agent MUST NEVER recommend editing, patching, or deleting generated `rendered-<pool>-<hash>` objects. All remediations must target the *source* `MachineConfig` CRDs via GitOps.
3. **Remediation Specification:** `playbook_match` MUST be `false` / `null`. Remediation must be output as `manual_cli_fallback`.

### Performance & Latency Targets
* Total graph execution time: $\le 45\text{ seconds}$.
* Splunk tool call count: $\le 2$ calls.

---

## 4. Prohibited Failure Modes
- **Failure Mode 1:** Recommending `oc edit mc rendered-worker-...`. (MCO will instantly overwrite it or break generation hash).
- **Failure Mode 2:** Failing to link conflicting source MachineConfig CRD names when cited in MCC logs.
- **Failure Mode 3:** Recommending node reboot to fix an ignition merge conflict.
