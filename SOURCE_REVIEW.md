# Source review and version caveats

This pack is based on a source review of the following upstream files as accessed on 2026-11-03:

- MCO drain controller: https://github.com/openshift/machine-config-operator/blob/main/pkg/controller/drain/drain_controller.go
- MCO drain controller tests: https://github.com/openshift/machine-config-operator/blob/main/pkg/controller/drain/drain_controller_test.go
- MCO daemon design: https://github.com/openshift/machine-config-operator/blob/main/docs/MachineConfigDaemon.md
- MCO daemon update implementation: https://github.com/openshift/machine-config-operator/blob/main/pkg/daemon/update.go
- MCCDrainError runbook: https://github.com/openshift/runbooks/blob/master/alerts/machine-config-operator/MachineConfigControllerDrainError.md
- OCP machine configuration overview: https://docs.openshift.com/container-platform/latest/machine_configuration/index.html

## Source-derived behavior

- The drain controller watches Node changes and uses the desired-drainer and last-applied-drainer annotations to coordinate work.
- A drain request is not complete until the controller successfully records the completion annotation. An externally uncordoned node during a drain is explicitly treated as unsafe to mark complete.
- The current upstream controller's default configuration defines a 90-second drain-helper timeout, a one-minute retry delay, a five-minute retry delay after a ten-minute failing threshold, and a one-hour drain timeout that emits a warning/degraded signal while continuing to retry. These are upstream defaults, not guarantees for every released OpenShift build.
- The drain helper is configured to ignore DaemonSet pods and delete emptyDir data. Its `Force` field must not be misread as permission to force-delete arbitrary pods from the API.
- The runbook calls out PDBs, storage unmounts, webhooks, and pod finalizers as common blockers. It documents force deletion and weakening/removing controls as possible mitigations, but this pack treats them as high-risk, approval-gated last resorts.
- MCO node updates include more than draining: node configuration application, optional OS pivot/reboot, verification, and uncordon can fail independently. Some changes can be rebootless or governed by NodeDisruptionPolicy.

## Version policy

The public `main` branch is a moving target. Before operationalizing this pack, compare its assumptions against the exact OpenShift release's MCO image/source tag and the matching Red Hat runbook. In particular, verify NodeDisruptionPolicy behavior, MachineConfigNode conditions, log wording, and timing constants for the deployed release. Commands are intended for `oc` access and initial triage; RBAC and API availability may constrain them.
