# Active worker runtime verification

## Acceptance boundary

On 2026-10-06 from 16:16:09 to 16:22:24 UTC, fourteen checks passed against
kind Kubernetes 1.37.0 with the alpha.6 candidate operator and worker.
The actual planner, Kubernetes client, worker, host locks, watchdog, reports
and finalizers ran. Only GPIO and thermal input were explicitly simulated.
This establishes software lifecycle behavior. Physical rotation, electrical
PWM, RPM, cooling stability and fault recovery require separate hardware evidence.

## Results

| Step | Observed result |
| --- | --- |
| Single fan | Synthetic 55 C input produced 47.5% requested duty; Fan and CoolingZone became Ready. |
| Worker identity | Correct Node placement and UID; service-account token automount disabled. |
| Multiple fans | Two GPIO channels on one Node were managed by one worker. |
| High temperature | Synthetic 80 C input produced 100% requests for both fans. |
| Missing sensor | Malformed input produced `LocalSensorUnavailable`, not Ready and 100% failsafe for both fans. |
| Recovery | Restored 55 C input returned both fans to Ready and 47.5%. |
| First fan retirement | Finalizer released normally; the removed simulated driver emitted `stop`; the remaining fan continued regulating. |
| Zone retirement | Finalizer released normally; the unassigned remaining fan requested 100%. |
| Last fan retirement | Finalizer released normally and the worker Pod disappeared. |

The fourteen individual checks and 113 timestamped status snapshots are in
[the raw report](runtime-lifecycle-alpha6.json). The
[GPIO call log](runtime-lifecycle-alpha6.txt) preserves the simulated driver
activity. ConfigMap projection contributed measured scenario delays of up to
89.53 seconds. This is an observation on this lab, not a guaranteed failsafe
latency for production.

## Retained initial failure

The initial alpha.5 trial failed before the worker process started. The kind
node had `/var/lock -> /run/lock` but no `/run/lock` directory. Containerd could
not create the hostPath through that dangling symlink. Preserve the
[failed trial](runtime-lifecycle-alpha5-failure.json) and
[kubelet events](runtime-lifecycle-alpha5-startup-failure.txt).

Preparing `/run/lock` restored the node prerequisite. Separately, the alpha.6
candidate mounts the existing `/var/lock/pifanctl` host directory at the direct
container path `/run/lock/pifanctl` and passes that path to the worker. The host
lock identity shared with legacy writers stays intact. Changing only the
container destination was not sufficient to fix the dangling host symlink.

The failed trial's deletion requests completed through normal reconciliation
after recovery. No finalizers were removed manually. The successful trial left
only the operator and original missing-node fixtures, with no lab Fan,
CoolingZone or worker Pod.

## Reproduction and supporting checks

Follow the [isolated lab instructions](../../tests/runtime_lab/README.md).
Never use the lab image on a hardware cluster. Its explicit marker and adapter
make it unsuitable for production publication.

The full local suite passed 320 tests without skips on Python 3.13.2.
The 24 focused tests also passed on Python 3.10. Statement coverage was
96.29%; branch coverage was 89.81%. Two loopback HTTP tests initially failed
under the filesystem/network sandbox and passed when rerun with socket access.
Helm lint, version checks, changeset validation and diff checks passed.
[Local verification](runtime-lifecycle-local-verification.json) records image
IDs and coverage totals. PR #57 CI [37495486653](https://github.com/jyje/pifanctl/actions/runs/37495486653) passed Python 3.10-3.14, coverage/Codecov, Helm/workflow/version checks and the ARC ARM64 image check. PR #57 merged at `74e9694`. Main CI [37495865042](https://github.com/jyje/pifanctl/actions/runs/37495865042), alpha.6 image publication [37495865690](https://github.com/jyje/pifanctl/actions/runs/37495865690), chart publication [37495865097](https://github.com/jyje/pifanctl/actions/runs/37495865097) and main coverage badge publication passed.

MicroK8s was not changed. Its operator, worker, four agents and topology CRs
remained Ready. Argo CD ordering, Kubernetes minimum-version coverage, live
API/image migration and rollback, fleet load and physical acceptance remain
release gates in [PLAN.md](../../PLAN.md).
