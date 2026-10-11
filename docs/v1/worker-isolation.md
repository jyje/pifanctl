# Worker isolation design

Status: proposal for [issue #86](https://github.com/jyje/pifanctl/issues/86). Nothing here is implemented or verified on a cluster unless a section says so.

## Why

Hardware workers run as root with `privileged: true` and the host `/sys` and `/dev`. On a Pi 4 this cannot be removed with Pod settings alone. A test on `raspi-40` showed that an unprivileged Pod gets `EPERM` on `/dev/gpiomem` and `/dev/gpiochip0` even with the right group, because the device cgroup ignores hostPath-mounted devices. See the [findings comment](https://github.com/jyje/pifanctl/issues/86#issuecomment-6109759442).

So the practical goal is to limit what a compromised operator or worker can do while workers stay privileged.

## Threat paths today

| Path | Today |
| --- | --- |
| A compromised worker | Root on its Node. It has no Kubernetes token. |
| A compromised operator | Its Role lets it create Deployments in the installation namespace. A Deployment can be a privileged hostPath Pod, so the operator can become root on any Node. |
| Other Pods in the installation namespace | The namespace must allow privileged Pods, so any Pod created there can be privileged. |
| Worker egress | Unrestricted unless the opt-in policy from #87 is enabled. |

## Correction to an earlier claim

Moving workers to their own namespace does not remove the operator path. The operator must still create worker Deployments, so it needs that right in the worker namespace. Separation only keeps the operator and agents out of a privileged namespace and shrinks the operator Role in its own namespace. Closing the operator path needs an admission policy (phase B).

## Phase A: separate worker namespace

- Add `--worker-namespace` to the operator and `workerNamespace` to the chart. Default: the operator's namespace, so behavior does not change.
- Worker Deployments, plan ConfigMaps, status ConfigMaps and the worker Service move to the worker namespace. The Lease stays in the operator namespace.
- Keep the ownership annotation `operatorNamespace/operatorId`. `worker_deployment` currently uses one `namespace` argument for both the object namespace and the annotation. Split them, or an operator in another namespace would refuse its own objects.
- Owner references point to cluster-scoped Fan and CoolingZone objects, which is valid across namespaces.
- RBAC: a Role and RoleBinding in the worker namespace for Deployments, ConfigMaps and Pods. The operator namespace keeps only Leases and Events.
- Pod Security labels: worker namespace `privileged`, operator namespace `restricted`.
- NetworkPolicies and ServiceMonitor follow the worker Service. The operator-to-worker ingress rule needs a `namespaceSelector` for the operator namespace.
- Migration: existing workers live in the operator namespace. Only one process may drive a GPIO pin, so retire the old worker before the new one starts. The expected effect is a short heartbeat gap, which already requests failsafe duty. Needs a live test with a rollback plan.

## Phase B: admission policy for operator-created Deployments

Use a `ValidatingAdmissionPolicy` (GA in Kubernetes 1.30, the declared minimum) bound to the worker namespace and matched on the operator ServiceAccount. It rejects any Deployment from the operator that is not the known worker shape:

- one container, image prefix `ghcr.io/jyje/pifanctl:v`, command starting with `python main.py worker run`
- no `initContainers`, `hostNetwork`, `hostPID` or `hostIPC`
- hostPath volumes only `/sys`, `/dev` and `/var/lock/pifanctl`, other volumes only ConfigMap
- `automountServiceAccountToken: false`

This turns "operator can create any privileged Pod" into "operator can create only a worker". Residual risk: a compromised operator can still start a worker with other flags or a different plan. The plan is validated by Node UID checks and hashes, but that is not a security boundary. Policy and binding are cluster-scoped, so the chart installer needs permission to create them. This should be opt-in at first.

## Phase C: device access without `privileged`

Deferred until A and B are done. Options from the #86 findings: a device plugin, CDI or DRA, or hardware PWM through sysfs. Each needs its own hardware test. None is claimed here.

## Verification plan

| Step | How | Status |
| --- | --- | --- |
| Phase A rendering and unit tests | Chart and operator tests with a separate worker namespace | Not run |
| Phase A lifecycle | Disposable cluster with simulated GPIO, including migration from the old namespace | Not run |
| Phase B policy | Disposable cluster: allowed worker shape passes, extra mounts, images and `hostNetwork` are rejected | Not run |
| Live migration | One Node with an archived rollback plan and a maintainer-approved window | Not run |

Any real fan behavior during migration stays Not measured until observed on hardware.

## Open questions

- Should the worker namespace be created by the chart or by the installer? Creating namespaces from a chart conflicts with the current "no namespace creation" RBAC stance.
- Should Phase B be on by default for new installs?
- Is a short failsafe window during migration acceptable for the existing rack?
