# v1 alpha runtime manual

**Implemented alpha, not a stable hardware release.** Application
`1.0.0-alpha.1` includes the portable schema/planner, freshness metric, guarded
worker, official Kubernetes client, operator, CLI and operator chart. Mock tests
do not establish real PWM behavior. [PLAN.md](../../PLAN.md) records the staged
checks and remaining release gates. [한국어](runtime-ko.md).

## 01: choose the physical topology

Use the [scenario figures](../../README.md#cooling-systems-manual-scenario-figures)
and [examples](../../design/v1/examples): two shared rack fans, per-board fans,
several fans on one Node, or standalone. One `Fan` is one actuator. One
`CoolingZone` selects cooled Nodes by labels or names and references its fans.
Shared fans use the union of all assigned zones plus their own local sensor.
There are no separate per-node member/worker CRDs.

```sh
PYTHONPATH=sources python sources/main.py topology validate design/v1/examples/standalone.yaml
PYTHONPATH=sources python sources/main.py topology plan design/v1/examples/standalone.yaml
# Selectors need live Node identity; this only reads the API:
pifanctl --context lab topology plan design/v1/examples/two-racks.yaml --live
```

`validate` checks shape and static relationships; `plan` preserves unresolved or
unhealthy relationships as explicit issues. Node objects must have Ready=True
to count as healthy. A complete explicit `v1/List` with `items: []` is valid
for retiring a topology. Empty files, duplicate keys, NaN and recursive aliases
are rejected. Pin/chip/channel/node are immutable for an existing Fan identity.
Release an old identity before reusing its channel with a new name.

Selector members removed from the Node API remain in the last expected set and
force full duty. A changed member Node UID is also retained as `NodeReplaced`,
since node-name-only telemetry cannot prove which physical board was replaced.
Review the rack inventory and replace the zone or explicitly change membership
to acknowledge the new identity. Live label edits can remove an existing Node
from membership intentionally. These guards survive operator restart in plans.

## 02: run a local worker

Install from the alpha source with its pinned requirements. The real worker
must run on its actuator host. `NODE_NAME` can map that host's actual Kubernetes
name; it must never be set to operate somebody else's hardware from a laptop.

```sh
# Run only on the actuator host after reviewing actual wiring and old writers:
sudo pifanctl worker run --file topology.yaml --node pi-01
# Safe development mode on a host with a test thermal directory:
pifanctl worker run --file topology.yaml --node pi-01 --mock \
  --thermal-path ./test-thermal --lock-dir ./test-locks --port 9103
```

Explicit nodeNames work offline. Selectors require `--live` and kubeconfig;
the file loader re-resolves Nodes on a file change. Operator mode re-resolves
labels continuously. Local YAML is polled and hot reloaded as a complete document;
use an atomic file replacement. A bad reload retains the old plan and forces
its fans to 100%. Hardware changes require a stopped/restarted worker after
claim release. A local worker does not require an operator heartbeat.

One host-wide `flock` at `/var/lock/pifanctl/worker.lock` covers all hardware
drivers, local CLI and Pods using the shared hostPath. This intentionally rejects
separate processes even on different pins. One process can own several fans.
The new legacy `start` command also locks; old v0 binaries do not. Stop them
before any migration. The sysfs driver leaves kernel PWM enabled on close;
RPi.GPIO stops its software thread and holds the pin HIGH. Verify actual
electrical full-speed behavior for your wiring before relying on this.

## 03: prepare Kubernetes

The alpha image is **not available merely because this PR exists**. Build and
publish it through the main pipeline after review, or supply a test image tag
that contains this code. Stable v1.0.0 still needs hardware acceptance.

```sh
helm lint charts/pifanctl-operator
helm template pifanctl charts/pifanctl-operator -n pifanctl-system
# On an explicitly selected review cluster after making the image available:
helm upgrade --install pifanctl charts/pifanctl-operator \
  -n pifanctl-system --create-namespace
pifanctl --context lab topology apply topology.yaml --dry-run
pifanctl --context lab topology apply topology.yaml
kubectl --context lab get fans,coolingzones
kubectl --context lab wait --for=condition=Ready fan/fan-01
```

The chart manages agents or reuses agents exporting
`pifanctl_temperature_observed_timestamp_seconds`. Prometheus must scrape **each
agent endpoint**, retain its `node` identity, and expose the API URL configured
in each zone. A single Service scrape against one backend is insufficient.
Enable ServiceMonitor only if the Prometheus Operator CRD and selectors exist;
otherwise configure per-Pod/Endpoint scraping. Old agents without read-time
metrics make remote zones unhealthy and request full duty.

Helm installs CRDs but does not upgrade them. Review and apply
`charts/pifanctl-operator/crds/` explicitly for future schema upgrades. Use
`design/v1/helm` to render topology CRs/ConfigMaps; it does not deploy runtimes.

## 04: ConfigMap mode and kubectl CLI

```sh
# Input ConfigMap and operator must share a namespace.
kubectl --context lab -n pifanctl-system apply -f design/v1/examples/configmap.yaml
helm upgrade --install pifanctl charts/pifanctl-operator -n pifanctl-system \
  --set input.mode=configMap --set input.configMapName=pifanctl-topology
pifanctl --kubeconfig ./lab.config --context lab fan list
pifanctl --context lab zone describe rack-a
pifanctl --context lab fan watch
kubectl pifanctl --context lab fan list
```

`install.sh` installs `kubectl-pifanctl`, which delegates to the same CLI.
Fan/zone commands address CR mode. ConfigMap mode leaves the input List in memory
and writes status to `pifanctl-status-<sha256(input-name)[:16]>` in the same
namespace. It does not create CRs. CR-mode `topology apply` uses server-side
apply, `fieldManager=pifanctl-cli`, `force=false`; `--dry-run` sends `dryRun=All`.
Apply is not transactional across several resources. For Helm/GitOps, edit the
authoritative source rather than forcing managed-field ownership.

## 05: verify convergence and failures

The operator renews a 30-second Lease before mutations. Node/CR watches wake
reconciliation; a five-second full resync recovers disconnects and detects
ConfigMap/workload/report changes. CR lists and Node lists are separate API
snapshots, not a transaction; cross-object changes may temporarily request full
duty. Operators claim CR metadata and refuse another operator's ownership.
One worker Deployment per actuator Node has Recreate/replicas=1, required name
and actual hostname affinity, and a plan containing Node UID. Workers have no
Kubernetes credentials. Leader loss stops heartbeat refresh.

CR-mode ownership records `namespace/operatorId`, so an identical ID in another
namespace cannot adopt the same CRs. This alpha uses one CR-mode installation
for the cluster-wide topology; replicas share its Lease.

ConfigMap directory projection can lag. The worker checks separate plan and
heartbeat files, matching hash and UID, allowing at most five seconds future
skew. **Watchdog default: 120 seconds**, chosen to tolerate common projection
delay; measure your environment. Projection lag can legitimately trigger full
duty. A healthy heartbeat does not bypass a zone's missing/stale sensor input.
The worker only decreases duty on each fan's refresh interval; rising demand
and failures are applied immediately when sampled.

A separate worker thread checks heartbeat expiry and control-loop progress every
second, independently of Prometheus queries. Its full-duty latch cannot be
overridden by a late query; the main loop must revalidate before clearing it.

| Observation | Meaning |
| --- | --- |
| `/status`, `/metrics` on worker :9103 | Applied hash, requested duty, member temperatures and reasons |
| `/healthz` | Process HTTP endpoint alive, not proof of cooling |
| `/readyz` | All desired fans are currently regulating safely; unhealthy returns 503 |
| Fan/CoolingZone `status.conditions[Ready]` | Fresh worker report with matching hash/UID and healthy inputs |
| Operator :9104 | `/healthz`, `/readyz`, `/metrics`; only the Lease leader is ready |

Reports must be at most 90 seconds old. Steady-state status writes are capped at
one per 30 seconds per object; readiness/reason/config changes are immediate.
Events are emitted on transitions and limited per reason in each process.
The alpha implements one Ready condition with detailed reasons; additional
diagnostic conditions and stock alert rules remain future enhancements.
Metrics contain node/fan/zone labels, never a stream of config-hash labels.
Duty is requested PWM, not RPM. The system does not detect a mechanically stuck
fan or guarantee power-loss cooling.

## 06: retire and migrate

Remove zones/Fans or the input ConfigMap while the operator remains running.
It publishes replacement plans and waits for matching worker acknowledgements.
A fan with no zone stays at 100%. Removing a Fan drives full duty, closes its
driver, and acknowledges a plan without that fan. For the last fan, the worker
Deployment is deleted and Pods must disappear before finalization. Empty-plan
acknowledgements survive operator restart in the ConfigMap until owner GC.
If other fans remain on the same Node, ownership transfers first. Unreachable
workers leave finalizers pending. A forced finalizer removal proves no hardware
safety and must be an explicit administrator decision.

Inventory wiring, compare a read-only plan, leave full duty, stop old v0 writers,
verify the processes are gone, then start the alpha on **one actuator host at a
time**. Roll back by stopping the alpha and releasing its lock before restoring
the legacy controller. Do not uninstall the operator before resources finish
release. Node/power loss, real Pi 4/Pi 5 PWM, server CEL/defaulting and fleet load
remain acceptance gates in PLAN.md. No operating cluster was changed by this work.
