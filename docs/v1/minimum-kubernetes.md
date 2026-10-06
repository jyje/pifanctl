# Minimum Kubernetes compatibility

## Scope and baseline

The declared Kubernetes API baseline is 1.30. A fresh kind cluster using
`kindest/node:v1.30.0` at digest
`sha256:047357ac0cfea04663786a612ba1eaba9702bef25227a794b52890dd8bcd692e`
passed nineteen real API checks and fourteen active worker lifecycle checks.
App alpha.6 and operator chart 0.1.0-alpha.5 were used. GPIO and thermal I/O
were explicitly simulated; the operator and worker runtime code was real.

The completed 1.37.0 cluster was archived before replacement. The new cluster
used a separate kubeconfig and the same guarded fixture context. MicroK8s and
the other project's kind cluster were unchanged.

## Checks

| Group | Result | Evidence |
| --- | --- | --- |
| CRD establishment and defaults | Passed for Fan and CoolingZone; temperature hysteresis default verified. | [API report](minimum-kubernetes-api.json) |
| Served API contracts | Invalid curve order, zero frequency and immutable Node/hardware changes rejected through both v1 and v1alpha1. | API report |
| Missing-node lifecycle | Expected failure statuses, release finalizers and cooperative cleanup passed. | API report |
| Active worker | Correct Node UID/placement, no worker credentials, one worker for two fans. | [Runtime report](minimum-kubernetes-runtime.json) |
| Control and failsafe | Synthetic hot input, missing local sensor and recovery passed. | Runtime report |
| Active claim retirement | Removed driver's stop, remaining fan regulation, zone retirement and final worker deletion passed. | [Simulated GPIO log](minimum-kubernetes-runtime.txt) |

The runtime trial ran from 16:31:09 to 16:36:55 UTC on 2026-10-06 and retained
101 timestamped samples. Every probe passed within its 160-second deadline.
No finalizers were forced off. Only the operator and original missing-node
fixtures remained after cleanup. The report records Kubernetes version, Node
identity and the actual worker image ID to distinguish recreated clusters.

Reproduction follows the [isolated runtime lab](../../tests/runtime_lab/README.md)
with the pinned node image above. Run `scripts/verify_release_api.py` with
`--exercise-lifecycle` before `scripts/verify_runtime_lifecycle.py` so the
API probe's no-worker check is meaningful.

## MicroK8s compatibility preflight

Workflow [37496692572](https://github.com/jyje/pifanctl/actions/runs/37496692572)
successfully built the alpha.6 Python 3.12 compatibility image. A nonprivileged
Pod using the existing operator service account performed only GET requests
against the current alpha API and generated a pure topology plan.

The probe passed with Python 3.12.15 and TLS verification enabled: four Nodes,
one Fan and one CoolingZone were read; the plan had no issues; no RPi module
was imported and no host volume was mounted. The Pod exited successfully,
was archived and was deleted. The active cooling configuration was unchanged.
See [the exact preflight record](alpha6-microk8s-read-only-preflight.json).

This is compatibility evidence for a read-only client. It does not prove a live
alpha.6 operator/worker rollout, stable API storage migration, Argo CD ordering,
rollback, physical waveform/RPM or thermal stabilization. Those remain in
[PLAN.md](../../PLAN.md). The primary Python 3.14 release image's compatibility
with the existing MicroK8s CA was not established by this Python 3.12 probe.

The full local Python 3.13.2 suite passed 320 tests with no skips after the report provenance change. Statement coverage remained 96.29% and branch coverage 89.81%. Changeset, version and diff checks passed. See [local verification](minimum-kubernetes-local-verification.json). Remote PR CI remains a separate merge gate.
