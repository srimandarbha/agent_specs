---
skill_id: 02-webhook-admission-failure
skill_version: 2.0.0
title: Fail-Proof Diagnosis for Admission Webhook Blocks Pod Eviction
lifecycle_stages:
- drain
- mcp_update
trigger_signatures:
- pattern: '(?i)(failed calling webhook|webhook.*denied.*eviction|admission webhook.*context
    deadline exceeded|x509: certificate.*webhook|connection refused.*webhook)'
  source: ocp_logs
- pattern: 'not_supported: no_webhook_admission_error_logged'
  source: ocp_logs
- pattern: "regex\n   (?i)failed calling webhook \"(?<webhook_name>[^\"]+)\": Post\
    \ \"(?<webhook_url>[^\"]+)\": (?<error_reason>.*)\n   "
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
  - Pod
  - Service
  - EndpointSlice
  - ValidatingWebhookConfiguration
  - MutatingWebhookConfiguration
  - Deployment
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
  negative: tests/fixtures/02-webhook-admission-failure/negative_dossier.json
  contradictory: tests/fixtures/02-webhook-admission-failure/contradictory_dossier.json
owner: platform-sre
status: draft
---

# Skill: Fail-Proof Diagnosis for Admission Webhook Blocks Pod Eviction (`02-webhook-admission-failure`)

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
| **Lifecycle Stage** | Node status is `SchedulingDisabled` (cordoned), and MCO is draining the node. | Exit: `inconclusive: lifecycle_stage_not_drain` |
| **Trigger Signal** | MCC or API-server logs match: `(?i)(failed calling webhook|webhook.*denied.*eviction|admission webhook.*context deadline exceeded|x509: certificate.*webhook|connection refused.*webhook)` on an eviction subresource call. | Exit: `not_supported: no_webhook_admission_error_logged` |

---

## 2. Step-by-Step Diagnostic Procedure (Deterministic Decision Tree)

```
                            [Start: Unified Splunk Dossier Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [Step 1: Extract Webhook & Interceptor]       [No Webhook Error Logged]
            Webhook name, failing pod, error string       ──► Exit: not_supported
                         │
                         ▼
            [Step 2: Interceptor Discrimination Gate]
            Is webhook virt-launcher-eviction-interceptor?
                         │
         ┌───────────────┴───────────────────────────────┐
         ▼                                               ▼
  [YES: KubeVirt Interceptor]                     [NO: Third-Party / Security Webhook]
  VM is not live-migratable!                      Proceed to evaluate webhook health
  ──► Handoff to 05-ocv-vm-not-migratable                 │
                         ┌────────────────────────────────┼────────────────────────────────┐
                         ▼                                ▼                                ▼
              [Connection Refused / 0 Endpoints]   [x509 Certificate Expired]      [Network Timeout]
              Webhook controller pod crashed       Serving certificate expired;    Apiserver-to-pod network
              or deployment unready                service-ca refresh needed       blocked by NetworkPolicy
              ──► Branch 3A: Backend Down          ──► Branch 3B: Cert Expired     ──► Branch 3C: Network
```

### Step 1: Extract Webhook Name & Blocker Pod
1. Extract `webhook_name`, `target_namespace`, and `failing_pod_name` from MCC or apiserver logs in `index=ocp_logs`:
   ```regex
   (?i)failed calling webhook "(?<webhook_name>[^"]+)": Post "(?<webhook_url>[^"]+)": (?<error_reason>.*)
   ```
2. Verify in `k8s_objects` / KV Store that `target_resource == failing_pod_name`.

### Step 2: Interceptor Discrimination Gate
1. **Check Webhook Identity:**
   * If `webhook_name == "virt-launcher-eviction-interceptor.kubevirt.io"`:
     * This is NOT an admission infrastructure failure. This is OpenShift Virtualization purposefully rejecting eviction because the virtual machine is not live-migratable.
     * **HALT IMMEDIATELY $\rightarrow$ Handoff to `use-cases/05-ocv-vm-not-migratable`**.
2. **If webhook is a general validating/mutating webhook (e.g. Gatekeeper, Kyverno, Vault, custom policy):**
   * Inspect error string and proceed to Step 3.

---

## 3. Causal Sub-Tree Analysis (The Root-Cause Engine)

```
                            [Admission Webhook Eviction Block]
                                            │
              ┌─────────────────────────────┼─────────────────────────────┐
              ▼                             ▼                             ▼
    [Branch 3A: Backend Down]     [Branch 3B: Cert Expired]     [Branch 3C: Network / Timeout]
    Pod in CrashLoopBackOff or    x509 certificate expired;     NetworkPolicy or egress firewall
    0 endpoints on webhook svc    apiserver mTLS rejected       blocks apiserver on port 443/8443
              │                             │                             │
              ▼                             ▼                             ▼
    Playbook: null (Risk)         Playbook: null (Security)     Playbook: null (Network)
    CLI Fallback: Fix Controller  CLI Fallback: Refresh Cert    CLI Fallback: Audit NetPolicy
```

* **Branch 3A: Webhook Controller Backend Down / 0 Ready Endpoints**
  * *Evidence:* Error contains `connect: connection refused` or `no endpoints available for service <webhook_svc>`. In `index=ocp_logs`, webhook controller pods are in `CrashLoopBackOff`, `Pending`, or scaled to 0 replicas.
  * *Diagnosis:* The admission webhook server is down. Because its `failurePolicy` is configured as `Fail`, kube-apiserver rejects all pod evictions matching the webhook's rules.
  * *Remediation Route:* **DO NOT delete the webhook configuration.** Route to **Manual CLI Fallback**:
    - Identify the crashing webhook deployment.
    - Provide commands to inspect logs, fix crashes, or scale up the webhook controller.

* **Branch 3B: Webhook Serving TLS Certificate Expired**
  * *Evidence:* Error contains `x509: certificate has expired or is not yet valid` or `x509: certificate signed by unknown authority`.
  * *Diagnosis:* The webhook server's TLS certificate (managed by OpenShift `service-ca` or cert-manager) has expired, preventing the API server from establishing a secure admission channel.
  * *Remediation Route:* **Manual CLI Fallback (Certificate Renewal)**. Rotate the webhook serving secret or trigger OpenShift service-ca re-injection.

* **Branch 3C: NetworkPolicy or SDN Route Blocking Apiserver-to-Webhook Traffic**
  * *Evidence:* Webhook controller pod is running and ready, but apiserver reports `context deadline exceeded` or `i/o timeout` connecting to `https://<service>.<namespace>.svc:443`.
  * *Diagnosis:* A restrictive `NetworkPolicy` in the webhook namespace or an egress firewall blocks inbound traffic from host-network control plane nodes to pod IP addresses.
  * *Remediation Route:* **Manual CLI Fallback (NetworkPolicy & Security Group Triage)**.

---

## 4. Remediation Resolution Rules

### Absolute Safety Rule on Admission Webhooks
> [!CAUTION]
> The diagnostic agent MUST NEVER execute autonomous playbooks to delete or disable admission webhooks (`oc delete validatingwebhookconfiguration ...`). Admission webhooks enforce enterprise compliance, image vulnerability validation, and security boundaries. Deleting webhooks exposes clusters to unvalidated workloads and compliance violations.

### Rule 1: Manual CLI Fallback Generation (Branch 3A - Webhook Backend Down)
**Triggered when:** Webhook controller pods are crashed or unready.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Admission webhook backend is offline; failurePolicy: Fail blocks all eviction requests.",
  "manual_cli_fallback": {
    "risk_level": "high",
    "pre_checks": [
      "# 1. Locate the failing webhook configuration and target service:",
      "oc get validatingwebhookconfigurations,mutatingwebhookconfigurations | grep -i {{ webhook_name }}",
      "# 2. Check endpoints and pod health for the webhook service:",
      "oc get endpoints -A | grep -i {{ webhook_service_name }}",
      "oc get pods -n {{ webhook_namespace }} -l {{ webhook_selector }} -o wide"
    ],
    "remediation_steps": [
      "# 3. Inspect webhook pod logs to identify why the server crashed:",
      "oc -n {{ webhook_namespace }} logs deployment/{{ webhook_deployment }} --tail=100",
      "# 4. Restart or scale the webhook deployment to restore service:",
      "oc -n {{ webhook_namespace }} rollout restart deployment/{{ webhook_deployment }}",
      "# 5. EMERGENCY ONLY (Requires security sign-off): Temporarily set failurePolicy to Ignore:",
      "# oc patch validatingwebhookconfiguration {{ webhook_name }} --type=json -p '[{\"op\":\"replace\",\"path\":\"/webhooks/0/failurePolicy\",\"value\":\"Ignore\"}]'"
    ],
    "safety_warning": "Changing failurePolicy to Ignore bypasses admission validation for all workloads. Ensure explicit security team approval before patching.",
    "verification": [
      "oc get endpoints -n {{ webhook_namespace }} {{ webhook_service_name }}",
      "oc get node {{ node_name }} -o jsonpath='{.spec.unschedulable}'"
    ]
  }
}
```

---

### Rule 2: Manual CLI Fallback Generation (Branch 3B - TLS Certificate Expired)
**Triggered when:** Webhook returns x509 certificate validation errors.

**Generated Output Spec:**
```json
{
  "matched": false,
  "reason": "Webhook serving TLS certificate expired; apiserver mTLS rejected.",
  "manual_cli_fallback": {
    "risk_level": "medium",
    "pre_checks": [
      "# 1. Inspect TLS secret expiration date:",
      "oc -n {{ webhook_namespace }} get secret {{ webhook_secret }} -o jsonpath='{.data.tls\\.crt}' | base64 -d | openssl x509 -noout -enddate"
    ],
    "remediation_steps": [
      "# 2. For OpenShift service-ca managed certificates, delete secret to trigger auto-regeneration:",
      "oc -n {{ webhook_namespace }} delete secret {{ webhook_secret }}",
      "# 3. Restart the webhook pod to mount the fresh certificate:",
      "oc -n {{ webhook_namespace }} rollout restart deployment/{{ webhook_deployment }}"
    ],
    "safety_warning": "Verify service.beta.openshift.io/serving-cert-secret-name annotation is present on the service before deleting secret.",
    "verification": [
      "oc -n {{ webhook_namespace }} get secret {{ webhook_secret }}"
    ]
  }
}
```

---

## 5. Fail-Safe Stop Conditions & Uncertainty Downgrades

The agent MUST halt and report `inconclusive` or `not_supported` if any of the following occur:

1. **Telemetry Ingestion Failure:** Splunk multi-index query fails or returns HTTP 5xx. Report: `inconclusive: telemetry_backend_unavailable`.
2. **KubeVirt Interceptor Present:** Webhook is `virt-launcher-eviction-interceptor`. Halt and hand off to `use-cases/05-ocv-vm-not-migratable`.
3. **Webhook Already Removed:** Webhook named in log error is no longer registered in cluster inventory. Report: `not_supported: webhook_already_removed`.
4. **Transient Network Hiccup:** Single timeout logged, but subsequent eviction calls succeed. Report: `not_supported: transient_network_timeout`.

---

## 6. Post-Remediation Verification Contract

Whether executed via webhook controller restart or certificate rotation, recovery MUST be proven using these exact signals:

1. **Webhook Endpoints Ready:** The webhook service reports at least 1 healthy, ready endpoint (`subsets.addresses` populated).
2. **Eviction Passes Admission:** API server logs in `index=ocp_logs` confirm eviction admission requests returning HTTP 200/201.
3. **MCO Drain Resumes:** MCC logs confirm node drain advancing past the blocked pod.
