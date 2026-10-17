# Worker isolation design

Status: Phases A and B are implemented in [PR #89](https://github.com/jyje/pifanctl/pull/89) and verified in a disposable Kubernetes 1.30 cluster. They are not verified on the live rack. Phase C is not started. Tracks [issue #86](https://github.com/jyje/pifanctl/issues/86).

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

Moving workers to their own namespace does not remove the operator path. The operator must still create worker Deployments, so it needs that right in the worker namespace. Separation only keeps the operator out of a privileged namespace and shrinks its Role in its own namespace. Narrowing the operator path needs an admission policy (phase B).

A second correction came from testing: the temperature agents are unprivileged but mount hostPath, which both `baseline` and `restricted` Pod Security reject. Agents therefore move to the worker namespace with the workers, and only the operator stays in the release namespace.

## Phase A: separate worker namespace

- Add `--worker-namespace` to the operator and `workerNamespace` to the chart. Default: the operator's namespace, so behavior does not change.
- Worker Deployments, plan ConfigMaps, status ConfigMaps, the worker Service and the agents move to the worker namespace. The Lease stays in the operator namespace.
- Keep the ownership annotation `operatorNamespace/operatorId`. `worker_deployment` currently uses one `namespace` argument for both the object namespace and the annotation. Split them, or an operator in another namespace would refuse its own objects.
- Owner references point to cluster-scoped Fan and CoolingZone objects, which is valid across namespaces.
- RBAC: a Role and RoleBinding in the worker namespace for Deployments, ConfigMaps and Pods. The operator namespace keeps only Leases and Events.
- Pod Security labels: worker namespace `privileged`, operator namespace `restricted`. Agents cannot run in a `restricted` or `baseline` namespace.
- NetworkPolicies and ServiceMonitor follow the worker Service. The operator-to-worker ingress rule needs a `namespaceSelector` for the operator namespace.
- Migration: existing workers live in the operator namespace. Only one process may drive a GPIO pin, so retire the old worker before the new one starts. The expected effect is a short heartbeat gap, which already requests failsafe duty. Needs a live test with a rollback plan.

## Phase B: admission policy for operator-created Deployments

Use a `ValidatingAdmissionPolicy` (GA in Kubernetes 1.30, the declared minimum) bound to the worker namespace and matched on the operator ServiceAccount. It rejects any Deployment from the operator that is not the known worker shape:

- one container, image prefix `ghcr.io/jyje/pifanctl:v`, command starting with `python main.py worker run`
- no `initContainers`, `hostNetwork`, `hostPID` or `hostIPC`
- hostPath volumes only `/sys`, `/dev` and `/var/lock/pifanctl`, other volumes only ConfigMap
- `automountServiceAccountToken: false`

This turns "operator can create any privileged Pod" into "operator can create only a worker". Residual risk: a compromised operator can still start a worker with other flags or a different plan. The plan is validated by Node UID checks and hashes, but that is not a security boundary. Policy and binding are cluster-scoped, so the chart installer needs permission to create them. This should be opt-in at first.

## Toleration scope

Worker Deployments tolerate every taint (`operator: Exists`) so a cooling worker still runs on a tainted control-plane or dedicated Node. Placement is still pinned to one Node by required node affinity on the hostname and Node name, and the plan carries the Node UID. A worker therefore cannot move to another Node, and the toleration does not widen where it runs. It does mean an operator-created worker can land on a Node that other workloads avoid, which is why the admission policy checks the worker shape.

## Phase C: device access without `privileged`

Decision (issue #90): workers stay `privileged: true` for now. This is an accepted risk, recorded here so it is a choice and not an omission.

Why it cannot be fixed with Pod settings: on a Raspberry Pi 4 (kernel 6.12, cgroup v2) an unprivileged Pod got `EPERM` on `/dev/gpiomem` and `/dev/gpiochip0` even with the right group, because the container runtime's device cgroup ignores devices that are only mounted through hostPath. The remaining routes each add something that needs host device access itself:

| Route | What it costs |
| --- | --- |
| Device plugin (a DaemonSet exposing the GPIO devices as Pod resources) | A new component that is itself privileged, so the risk may only move |
| CDI or DRA | Runtime configuration and a driver, new moving parts on every Node |
| Hardware PWM through sysfs (`SysfsDriver`, `dtoverlay=pwm`) | A host boot config and wiring change, and the tachometer still opens `/dev/gpiochip*` |

None of these was built or tested, so no claim is made about them.

What limits the damage instead (all in `main`, all off by default except where noted):

- Workers have no Kubernetes token and are pinned to one Node by affinity and Node UID.
- `workerNamespace` keeps the privileged Pods out of the operator's namespace, so only the operator needs to be `restricted`.
- `workerAdmission.enabled` limits what the operator can create there to the known worker shape.
- `networkPolicy.workerEgress.enabled` limits worker egress to DNS and Prometheus. Because a host escape bypasses Pod network policy, treat it as defense in depth.
- The operator Role in its own namespace holds only Leases and Events when workers are separated.

Seccomp and `allowPrivilegeEscalation: false` stay unset on workers, because the API rejects the second together with `privileged` and privileged containers ignore seccomp.

Revisit when any of these changes: a worker needs to run on shared or untrusted Nodes, the Pi OS or runtime stops ignoring hostPath devices in the device cgroup, a maintained GPIO device plugin or CDI spec appears, or the rack moves to hardware PWM for other reasons. A candidate must be tested on Pi 4 and Pi 5 hardware with a rollback plan, and anything not measured must stay marked Not measured.

## Verification

Disposable kind cluster on Kubernetes 1.30.0 (the declared minimum), with the real operator code running under the operator ServiceAccount token. No hardware and no live cluster.

| Step | Result |
| --- | --- |
| Policy compiles on 1.30 | Failed first: `slice` is missing from the 1.30 CEL library. Fixed with element comparisons |
| Real worker Deployment | Admitted |
| 12 tampered Deployments | All denied |
| Same tampered object as cluster admin | Admitted, so only the operator is constrained |
| Operator Role split | No Deployment or ConfigMap rights in the release namespace, Lease rights there, worker rights only in the worker namespace |
| Two reconcile passes | Objects in the worker namespace, Lease in the release namespace, own objects adopted on the second pass |
| Pod Security | Privileged Pod rejected in `restricted`. Worker and agent run in `privileged`. Operator Pod admitted in `restricted` |
| Deletion with a worker acknowledgement | Unit test only. The kind worker has no GPIO and cannot acknowledge |
| Migration of the live rack | Not run |
| NetworkPolicy rule on a CNI that enforces it | Not run |

Any real fan behavior during migration stays Not measured until observed on hardware.

## Decisions

- The installer creates and labels the worker namespace. The chart does not create namespaces, which keeps its "no namespace creation" RBAC stance. The README and runtime manual show the commands.
- Phase B stays opt-in until it has run on the live rack. It needs cluster-scoped permission to install.
- Old worker Deployments are removed by hand after a move, which avoids giving the operator delete rights in its own namespace. A short failsafe window on the live rack needs a maintainer-approved time and a rollback plan.
