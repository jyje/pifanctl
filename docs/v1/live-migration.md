# Live CRD storage and runtime migration

## 01: acceptance boundary

The four-node MicroK8s rack exercised the actual alpha.6 operator and GPIO worker,
archived alpha.3 image rollback, CRD storage promotion and full reverse storage
restoration. The fan remained under its existing configuration: GPIO18 on
the original fan host, one CoolingZone for four members, 50-75 C curve, 5 C hysteresis,
5-second refresh and 100% failsafe/exit commands. No load, fan-off stimulus or
physical wiring change was applied.

This is software and live runtime acceptance for this existing rack. It does
not measure electrical PWM, RPM, airflow or cooling capacity, repeat the complete
v0 topology rollback, establish target-temperature stability, or extend hardware
support to untested configurations. The earlier visual rotation confirmation
was for alpha.3, not a new physical measurement during these trials.

## 02: archive and freeze

The original v0 archive passed all 25 file checksums. Current Application, CRDs,
Fan/CoolingZone and non-secret runtime objects were archived before mutation.
The private trial archive retains checksums, snapshots and failed attempts.
Public records contain anonymous node labels, temperatures, source times and
check results. They exclude full Kubernetes objects, resource names/UIDs, IPs,
service URLs and configuration. Originals remain in the private archive.
`scripts/redact_live_evidence.py` reproducibly projects those summaries; its
privacy tests reject identifier/error disclosure. The published summaries do
not provide independent access to the private identity snapshots.

[Cluster PR #148](https://github.com/jyje/cluster/pull/148) pinned the published
operator chart 0.1.0-alpha.6 at `e04f73b53e52050a31da274723a8d4b2ca8e61a1`,
selected the verified Python 3.12 image and disabled child automatic synchronization.
The parent delivered that manual policy before the storage trial began. The
alpha.3 worker continued regulating during the storage-only steps.

The Python 3.12 compatibility image is intentional: the cluster's legacy CA
profile previously failed strict Python 3.13/3.14 verification. The alpha.6
preflight and subsequent runtime use normal TLS verification, not a bypass.
See [minimum compatibility](minimum-kubernetes.md).

## 03: storage round trip

| Step | Recorded outcome | Evidence |
| --- | --- | --- |
| Promote while alpha.3 remains active | Dual served endpoints installed; every resource rewritten to v1 before storage history was cleared | [Initial round trip](live-storage-roundtrip.json) |
| Reverse the initial promotion | Alpha storage rewrite and original alpha-only definitions restored; original worker UID and resource identities preserved | Initial round trip |
| Later independent reverse trial | Both original alpha-only specs and alpha storage declarations/history restored; CRD UIDs and rollback-worker UID preserved | [Reverse verification](live-storage-reverse.json) |
| Final complete promotion | Both resources rewritten; v1 declaration and stored history verified; fresh observations and original worker UID retained | [Promotion verification](live-storage-promotion.json) |

The storage verifier requires explicit `--execute`, the MicroK8s context, manual
Application sync and no active operation. It inventories exactly the declared
rack Fan and CoolingZone, rejects retiring/unready resources, checks temperature
and heartbeat freshness, and archives before mutations. Reverse restoration
checks the archive checksum and CRD UID. Rewrites use fresh resource versions,
retry conflicts and reject topology/identity changes. History is never cleared
before every rewrite and the complete inventory check succeed.

It keeps the alpha endpoint served through each direction and reads it directly
to avoid cached preferred-version discovery after rollback. It never deletes a
CRD, clears a finalizer or starts another worker. A failure preserves served
endpoints and diagnostic state for an inspected recovery.

## 04: candidate and image rollback

The candidate is `ghcr.io/jyje/pifanctl-issue:cbc8958-py312` with digest
`sha256:774e8355d08ba18bcca660c4045d7dfc8f3ed25e77661c305f97c97ea387f49f`.
The archived image is `69a829f-py312`, digest
`sha256:1bbee7f514a3547ac9c0b1413f159f077f4ed90821ff2d39080119f3cd528115`.

| Trial | Observed hold | Evidence |
| --- | --- | --- |
| Initial alpha.6 deployment | 121.6 seconds, 22 observations | [Candidate hold](live-runtime-candidate.json) |
| Alpha.3 runtime image rollback | 62.6 seconds, 12 observations | [Rollback hold](live-runtime-rollback.json) |
| Restored alpha.6 with self-heal | 120.6 seconds, 22 observations | [Final hold](live-runtime-restored.json) |

[Cluster PR #149](https://github.com/jyje/cluster/pull/149) restored the archived
image through manual GitOps synchronization, retaining dual APIs, the same
operator identity and unchanged v1 instance specs. Both image holds verified
current Argo source/revision success, one worker, no legacy controller, resource
UID/spec preservation, exact image digest, direct worker readiness/heartbeat,
Node UID, applied plan hash, credential absence and the shared host lock path.
Worker replacement uses Recreate. Snapshot checks do not measure subsecond
handoff timing or electrical shutdown behavior.

Every observation also records each member's temperature and original source
clock. `timestamp(metric)` is evaluated before aggregation; the instant query
evaluation time is not treated as a sensor observation time. All member source
ages must be at most 30 seconds, direct worker age at most 15 seconds, and every
member must remain below 65 C. The verifier is read-only and changes no fan
commands or workloads.

## 05: excluded attempts and verifier corrections

Two initial stale preflights performed no mutations. A later successful storage
rewrite failed its immediate published-heartbeat freshness check at 20.385
seconds against a 20-second limit. That [original failed report](live-storage-promotion-failure.json)
remains failed. CR status publication is intentionally throttled to 30 seconds;
subsequent storage observations wait boundedly for a fresh snapshot without
relaxing the age limit. These are sampled healthy states, not uninterrupted
measurement between observations. Runtime holds use direct source clocks.

The first runtime observer's Pod proxy request returned 404 because kubectl's
request-timeout query reached the worker's exact `/status` route. Removing the
proxy query while retaining a bounded subprocess corrected the observer. The
failed attempt is excluded; the complete repeated candidate hold passed.
The [excluded-attempt audit](live-migration-excluded-attempts.json) preserves both
limitations rather than overwriting them with successful runs.

## 06: reproduction and local regression

Use `scripts/verify_live_storage_migration.py` with explicit context, Application,
Fan/zone names, new archive/report paths and `--execute`. Modes are `roundtrip`,
`promote`, and `reverse`; reverse also requires the original `--restore-archive`.
Never run it during automatic synchronization or topology edits. Coordinate
image changes through the reviewed GitOps source, not direct Deployment edits.

Use `scripts/verify_live_runtime.py` for read-only holds, specifying the exact
revision, image/digest, archived baseline, report and at least 60 seconds.
Each subprocess is bounded. Failure reports are written without restarting the
trial or silently resetting an established hold.

The final full Python 3.13.2 suite passed 368 tests without skips. Related Python
3.10 checks passed 44 tests. Statement coverage remained 96.29%, branch coverage
89.81%. [Local verification](live-migration-local-verification.json) records
these results. Remote PR checks and merge are independent gates.

## 07: release decision

[Cluster PR #150](https://github.com/jyje/cluster/pull/150) restored alpha.6 and
automatic self-heal. A further 120.6-second source-aware healthy hold passed.
Both CRDs store v1, the v1 instance manifests remain declared, and one actual
worker regulates the existing rack. Candidate restoration and automation
recovery are complete for this software migration window. Thermal targets, electrical/RPM
measurements, hardware failure cases and fleet size remain in [PLAN.md](../../PLAN.md).
Do not publish a stable v1 release from these runtime holds alone.
