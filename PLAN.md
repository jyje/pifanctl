# pifanctl v1 implementation plan

## Goal and scope

The application was v0.2.1 when this work began. The goal is v1: require CRDs to
select cooling members by Node labels or names and manage CoolingZones and
physical Fans. Declare instances through the operator chart's `extraResources`
values in the GitOps Application. Implement the worker, Kubernetes operator,
cluster-aware CLI with kubeconfig/context support, and a single operator chart.
Standalone fan control and ConfigMap topology input are outside the v1 contract.

The first implementation is `1.0.0-alpha.1`. Automated checks use mock drivers,
fake sensors, Prometheus and Kubernetes APIs, and temporary files. Live deployment
and hardware experiments require explicit user authorization. Operational plans,
archives, and findings belong in the private operations archive.

The maintainer approved practical verification closeout on 2026-10-07 for the
observed mixed Pi 4/Pi 5 rack. Proceed with release preparation; remaining
hardware and extended scenarios below are deferred follow-up, not passed checks.
Local and CI results alone do not establish electrical cooling safety.

## Work rules

1. Implement stages in order. Validate the preceding stage before committing the next stage.
2. Remove a completed stage from the pending checklist only after all its checks pass. Record changes, actual evidence, and limitations in the completion log.
3. Commit implementation, its tests, and the PLAN update together. Identify the commit by message initially, then add its SHA in the next update.
4. Stage only files owned by this task. Review the diff and version gate.
5. Live deployment, physical fan control, PR merge, and stable release each require applicable user authorization. Preserve authorization already given in the conversation.
6. Repair failed checks and rerun them. Never describe skipped checks as passing.
7. Share progress and update the design documentation when implementation changes the design.
8. Write primary documents, issues, commits, and PRs in English. Translations belong in explicit locale files, as required by AGENTS.md.

## Status

- Design and diagrams: [PR #40](https://github.com/jyje/pifanctl/pull/40), merged into `main` at `1bc4e55`
- v1 implementation roadmap: [issue #39](https://github.com/jyje/pifanctl/issues/39)
- Implementation branch: `feat/v1-topology-runtime`, [PR #41](https://github.com/jyje/pifanctl/pull/41), merged into `main` at `eb77c0c`
- Coverage CI follow-up: issue #42 completed by [PR #43](https://github.com/jyje/pifanctl/pull/43), merged into PR #41 at `6dc6bfa` and included in `main` at `eb77c0c` on 2026-10-04.
- Coverage badge assets: [PR #44](https://github.com/jyje/pifanctl/pull/44), merged into `main`; generated assets live under `assets/coverage/`.
- Candidate API: `pifanctl.jyje.online/v1`, cluster scoped Fan and CoolingZone, with served `v1alpha1` compatibility. Live MicroK8s serves both APIs with v1 storage and the verified alpha.6 Python 3.12 compatibility operator/worker; alpha.2 temperature agents remain reused.
- Diagrams: shared fans and one fan per board, each with normal, hot, missing-data, and expired-heartbeat scenarios in English and Korean locale files

## Pending checklist


Stages 01-08 have completed implementation, mock verification, sequential commits,
and PR submission, so their pending entries have been removed. The live alpha.3
worker deployment and bounded 55°C response observations are recorded in the release
acceptance manual. Normal visual fan rotation was confirmed before the load run. Other temperature
targets, RPM, electrical measurements, and failure acceptance remain open.

## Release preparation and deferred verification backlog

### v1 packaging and release preparation

- [x] Set the v1 product contract: CRDs are required, standalone fan control is out of scope, and one operator chart owns the runtime.
- [x] Add `extraResources` to the operator chart so the GitOps Application can declare its `Fan` and `CoolingZone` instances.
- [x] Keep app and chart version checks independent and publish only the supported operator chart from the v1 chart workflow.
- [x] Align primary v1 docs with CRD-only topology and the single-chart packaging model.
- [x] Remove ConfigMap topology selection and `--configmap` from the operator chart and CLI interface.
- [x] Remove standalone `start` and its legacy router from the v1 CLI. Require `--mock` for local YAML workers; retain operator plan/UID/heartbeat execution. Replace image smoke tests with a direct driver-refusal probe and move v0 instructions to the legacy archive. Local verification is recorded in the completion log; remote CI is checked before merge.
- [x] Update the `jyje/cluster` Argo CD Application to the operator chart and declare the four-node rack topology in `extraResources`.
- [x] Verify CRD establishment, custom-resource admission, Argo CD ordering, live Fan/CoolingZone reconciliation, and worker placement on MicroK8s.
- [x] Verify CRD establishment/defaulting/admission and missing-node operator reconciliation on a disposable Kubernetes cluster: fifteen checks passed on kind Kubernetes v1.37.0 with a separate kubeconfig. See `docs/v1/release-api-verification-2026-10-07.json`.
- [x] Verify disposable-cluster Argo CD ordering, active worker reconciliation, and finalizer/deletion lifecycle for active hardware claims: seventeen checks passed through real Argo CD 3.5.2 and Kubernetes 1.30.0 with explicitly simulated GPIO/thermal I/O. This verifies declared runtime claims and staged background pruning, not physical hardware behavior. See `docs/v1/gitops-lifecycle.md`.
  - [x] Verify active worker software lifecycle using explicitly simulated GPIO/thermal I/O: fourteen real Kubernetes checks passed, including two fans per worker, Node UID/credential isolation, sensor loss/recovery and cooperative Fan/CoolingZone deletion. See `docs/v1/runtime-lifecycle.md`. Hardware behavior remains open; Argo ordering is now verified separately above.
- [x] Promote the candidate CRD API to `v1`, retaining served `v1alpha1` with identical schemas. Verified complete resource rewrites, UID/spec/finalizer/status preservation and reverse storage rollback in kind; nineteen real dual-version admission/lifecycle checks passed. See `docs/v1/api-migration.md` and its evidence reports.
- [x] Verify the candidate operator/worker image with the stable API, production storage migration/reverse rollback, minimum Kubernetes version and live GitOps instance conversion. Alpha.6 candidate and alpha.3 archived-image holds passed, then alpha.6 and self-heal were restored with a further 120.6-second healthy hold. This closes software migration for the current rack, not full v0 topology or supported-hardware rollback acceptance. See `docs/v1/live-migration.md`.
  - [x] Verify declared Kubernetes 1.30 minimum software compatibility: nineteen real API checks and fourteen active runtime checks passed on 1.30.0 with explicit simulated I/O. See `docs/v1/minimum-kubernetes.md`.
  - [x] Verify the alpha.6 Python 3.12 compatibility image can read the live alpha API and build a valid four-node topology plan with TLS verification enabled and no GPIO import. This read-only preflight does not pass live runtime/migration acceptance.
  - [x] Exercise live storage promotion and reverse rollback, preserving CRD/resource UIDs and the active worker. Complete v1 re-promotion passed with explicit declaration/history verification.
  - [x] Verify actual alpha.6 runtime for 121.6 seconds and archived alpha.3 image rollback for 62.6 seconds with direct worker and per-member source clocks. These are runtime holds, not thermal stability tests.
  - [x] Restore candidate image and automatic self-heal, then verify another source-aware healthy hold: 120.6 seconds, 22 observations. Cluster PR #150 merged at `fbdb9d2`; source-matched Argo Synced/Healthy, v1 storage and one worker verified.
- [x] Close the current practical verification campaign by maintainer approval; retain unmeasured hardware, physical failures and extended fleet scenarios as deferred follow-up.
- [ ] Prepare and publish app `1.0.0` and operator chart `1.0.0` with the verified scope and deferred limitations in release notes; keep later app/chart versions independent.

- [x] Merge design PR #40 and implementation PR #41 into `main` in dependency order.
- [x] Verify the first successful main line and branch badge publication under `assets/coverage/`.
- [x] Record direct visual confirmation of normal shared-fan rotation for the active alpha.3 deployment. The user confirmed continuous blade rotation; RPM, waveform, and stop/restart behavior remain unmeasured. See Section 12 of the acceptance manual.
- [ ] Measure real Pi 4 GPIO and Pi 5 sysfs wiring, channel, initialization and shutdown PWM behavior.
- [x] Pass the existing 50 C fixed-load observation under the approved `v1-3c` policy: 140.24 seconds within 49-52 C, measured span 2.75 C, duty 35.04%, complete acquisition clocks and cooldown. This is a post-hoc reassessment, not a new trial. See Section 16.
- [ ] Pass the 60 C controlled-load stability gate under `v1-3c`. The new fixed 1000m, 360-second trial completed with complete clocks and immediate cooldown, but its remote peak 58.4 C stayed below the 59 C observation lower bound. Local peak 61.15 C stayed below the 65 C local cutoff. RPM remains a separate instrumentation gate.
- [ ] Pass the 55 C controlled-load stability gate under `v1-3c`. Fresh 500m, 750m and 600m trials retained every member acquisition clock but failed the 120-second hold. Longest qualifying interval: 65.42 seconds. Both higher loads stopped at the independent 60 C local guard. See Section 17 of the acceptance manual; RPM remains unmeasured.
- [ ] Measure fan behavior during process kill, Node reboot, power loss, and network partition.
- [ ] Complete supported hardware migration and rollback acceptance across the documented configurations.
- [ ] Measure status, Prometheus, and API load at the supported fleet size.
- [x] Document electrical fail-open limits and independent fan power requirements. Hardware-specific measurements remain open above.

The repeatable procedures, acceptance criteria, current MicroK8s baseline,
evidence form, and release decision record are in the [v1 release acceptance
field manual](docs/v1/release-acceptance.md) and its [PDF](docs/v1/release-acceptance.pdf).
The 2026-10-04 load trial used a Python 3.12 compatibility image because the
cluster uses the documented legacy-CA path. The alpha.2 shared-fan response check
on 2026-10-06 used an 85-second 1 vCPU load, then stopped a 2 vCPU stage after a
15-second poll observed 61.15°C. The hottest node returned to 46.85°C during a
three-minute no-load observation. This was not stable-temperature or v1 worker
acceptance. See the [follow-up record](docs/v1/release-acceptance.md#7-2026-10-06-live-shared-fan-follow-up),
its [CSV](docs/v1/thermal-load-observations-2026-10-06.csv), and [plot](docs/v1/figures/thermal-live-2026-10-06.png).

An isolated alpha.3 runtime probe then established the Fan and CoolingZone CRDs,
admitted both CRs, confirmed API defaulting, and reconciled expected missing-node
conditions with Argo CD Synced/Healthy. The alpha.3 Python 3.12 ARM64 image passed
its experimental issue-image workflow (run 37429082468). No worker or GPIO Pod
was created, and the temporary CRs, Application, and namespace were removed. The
production application remains alpha.2 with one controller on `raspi-40` GPIO18
and four agents. This validates API/operator behavior only. A GitOps single-writer
handoff, v1 worker startup, direct fan rotation, temperature stabilization,
failure recovery, electrical PWM/RPM, and rollback acceptance remain open. See
the [isolated probe record](docs/v1/release-acceptance.md#8-2026-10-06-isolated-alpha3-crd-runtime-probe).

The safe single-writer GitOps handoff is active in MicroK8s. Merged cluster PRs
#144, #145, and #146 installed the alpha.3 operator, disabled the alpha.2
controller, and enabled app-scoped pruning. Cluster PR #147 then declared the
GPIO18 Fan on `raspi-40` and a CoolingZone covering all four Raspberry Pis. Argo
CD is Synced/Healthy, the worker is Ready on `raspi-40`, and both CR statuses are
Ready. The user visually confirmed normal rotation after the update and before
the test. A bounded
1 vCPU load on `raspi-51` then held the rack maximum in the 54–56°C band for 144
seconds at 50.44% requested duty. The temporary Pod was removed; a later
read-only check found the operator, worker, Fan, and CoolingZone Ready, with no
load Pod present. This records a 55°C target-band response; the original stability criterion remains open. RPM, electrical
waveform, the 50°C and 60°C targets, immediate cooldown curve, and fault recovery
remain open. See the [worker record](docs/v1/release-acceptance.md#9-2026-10-06-alpha3-shared-rack-worker)
and [55°C stability record](docs/v1/release-acceptance.md#10-2026-10-06-alpha3-55c-shared-rack-stability-run).

## Release verification sequence (2026-10-07)

1. Recheck PRs, CI, source revisions, and the live single-writer deployment.
2. Derive every thermal verdict from retained samples with `scripts/verify_thermal_acceptance.py`. Use approved `v1-3c`: 120 seconds within target - 1 C through target + 2 C, at most 3 C total variation, complete fresh per-member acquisition timestamps, and at most 5 percentage points of duty variation. Preserve the original `legacy-1c` evaluator and failed results.
3. Establish a disposable Kubernetes cluster using a separate kubeconfig. Validate CRD admission/defaulting/CEL rejection, chart ordering, reconciliation, finalizers, and deletion without physical GPIO access.
4. Remove unsupported standalone CLI routes, then validate the Kubernetes CLI and worker entry points. Promote the stable CRD API only after a tested alpha-to-stable migration path exists.
5. Repeat controlled thermal targets with bounded load, server-side deadlines, temperature and freshness guards, guaranteed cleanup, and immediate cooldown capture.
6. Exercise reversible telemetry and operator failures with restored configuration and compare expected/actual status and duty. Test worker termination and rollback with archived manifests and one hardware writer.
7. Measure declared fleet sizes in the disposable cluster. Record API traffic, reconciliation/status latency, CPU/memory, and errors.
8. Capture electrical PWM, fan hardware identity, Pi 5 channels, RPM, and actual reboot/power-loss behavior with physical instrumentation. Remote software evidence cannot satisfy these measurements.
9. Regenerate and inspect the final report and PDF, verify release changesets/app/chart versions, and merge passing PRs. Stable release remains gated on every applicable requirement.

## Current release audit evidence

- Final local Python 3.13.2 regression: 303 tests passed with zero skips after installing the pinned Matplotlib development dependency. Statement coverage: 95.87%; branch coverage: 89.10%; combined: 94.19%. JUnit-derived evidence and tested-tree hashes are recorded in `docs/v1/release-local-verification-2026-10-07.json`. An initial sandbox-only run could not bind loopback sockets; rerunning with loopback access passed both HTTP integration tests.
- Thermal evidence verifier: fourteen regression checks passed. Re-evaluation retains 144 seconds in the target band but only 75 seconds within the original 1°C total-range criterion. Per-member source clocks are absent from the old CSV, so no stability certificate is issued.
- Disposable kind cluster: Kubernetes v1.37.0, alpha.3 compatibility operator, fifteen real-API and missing-node finalizer lifecycle checks passed. Helm 4 default waiting timed out on intentionally missing-node fixtures; installation with custom-resource waiting disabled completed. This does not establish healthy worker readiness or Argo ordering.
- PR #53 merged as `146e1c8` after updated-head CI run `37486914215` passed Python 3.10-3.14, chart/workflow/version checks, ARC ARM64 image smoke checks, and Codecov project/patch statuses.
- Direct physical observation: the user confirmed continuous normal fan rotation. A read-only follow-up reported 38.12% requested duty and 49.05°C rack maximum with Ready operator, worker, Fan, and CoolingZone. This passes the visual observation check only.

## Completion log

| Stage | Changes and verification | Commit |
| --- | --- | --- |
| Initial design | CRDs, examples, English/Korean design; PR #40 CI passed. No runtime yet. | `e31e183` |
| Diagrams and version correction | 16 SVG/PNG pairs, eight scenarios in each localized README, v1 naming and paths. PNG visual review and diff check passed. | `dc01b03` |
| 01 | Schemas/defaults, strict YAML validation, label/name planner, conflicts, failsafe and hashes. 153 tests passed; coverage deferred to integration. Application and legacy chart alpha versions aligned. | `03290da` |
| 02 | Agent observation timestamp, exact-label freshness, complete zone membership and local floor, missing/stale/outage handling. 30 telemetry/service tests passed. | `01e1a17` |
| 03 | Worker multi-fan/full-duty/reload/watchdog/report, host lock shared with legacy CLI, GPIO thread release and chart hostPath. 182 full tests and 36 focused tests passed. Cooperative host lock; physical PWM was not measured at this stage. | `19c27ff` |
| 04 | Official client/context, bounded API, SSA/dry-run, topology/fan/zone/worker CLI and kubectl wrapper. 188 tests passed. Local files compile once; selectors require --live. | `395e6fb` |
| 05 | Lease leadership, CR/ConfigMap planner, Node/UID pinned worker Deployment, plan/heartbeat, ownership and watch/resync. Six fake API tests passed. Agent managed/reuse packaging follows in stage 07. | `3aa1018` |
| 06 | Observed hash/UID status, rate limits/Events, finalizers, ownership transfer and durable empty-plan acknowledgements. Eleven fake API tests passed; unreachable workers remain pending. | `b0bdc82` |
| 07 | Operator chart, RBAC, NetworkPolicy, agents and CRDs; localized runtime/migration docs; alpha prerelease/latest safeguards; local YAML reload and sticky member UID. Helm lint for both inputs/topology, kubeconform for nine operator resources and one worker, actionlint, and 49 focused Python 3.10 tests passed. Added CI matrix regression coverage. | `3921b92` |
| 08-a | All five Python versions: 218 tests, 93.88-93.91% coverage. Real client/fake HTTP and shared-rack integration exposed argument and method-name conflicts, which were fixed. After robustness changes: Python 3.14, 218 tests, 93.48%. Kubernetes 1.30/1.33 kubeconform and actionlint passed. | `f8e6dcb` |
| 08-b | PR #41 created and attached; first remote CI passed nine jobs. Added per-board/multi-fan/watch recovery tests: 224 tests, 95.69%. Independent watchdog latch protects delayed queries; 22 focused and 227 full tests passed, 95.65%. Query latency counts toward sample age. Remote CI passed all nine jobs. | `f08e04e` |
| 08-c | Namespace/operator ID ownership rejects adoption by the same operator name in another namespace. 18 focused tests passed. All five Python versions: 228 tests, 95.66-95.68%. Remote CI passed nine jobs. | `33f5955` |
| 08-d | ConfigMap owner-reference admission grants finalizer updates only on the selected input ConfigMap. Twelve chart tests/lint and Python 3.14 full suite passed: 228 tests, 95.66%. Localized background deletion instructions added. Remote CI passed nine jobs. | `92a142b` |
| 08 complete | Preserve five Python versions and the 90% gate. Remote CI: 228 tests, 95.72-95.74%, nine jobs including ARM64/chart/workflow/version. Localized README alpha/chart publishing descriptions aligned; issue #39 and PR #41 evidence updated. | `0296adf` |
| CRD admission follow-up | Real API rejected an empty curve default because CEL operands were absent. Materialized defaults in both CRD copies and the shared schema. API defaulting and five invalid curve/immutable updates verified. Local Python 3.14: 229 tests, 95.66%. | `4a9cfe7` |
| Runtime image follow-up | Supported Python runtime selection for strict X.509 and legacy CA compatibility. Isolated SHA-py312 tags; alternate runtimes cannot publish latest/release tags. CI retains Python 3.10-3.14. actionlint and Python 3.14 full suite passed: 233 tests, 95.66%. | `2b58d9a` |

| v1 support and release preparation | PR #51 adds operator-chart `extraResources` rendering and schema validation for Fan/CoolingZone instances. Removed ConfigMap topology selection from the supported operator interface, aligned v1 docs, bumped the app to `1.0.0-alpha.3`, made app/chart versions independent, and limited chart publishing to the operator chart using its pinned `appVersion`. Python 3.13: 288 passed, 1 skipped, 94.19% line coverage; Helm lint/render, actionlint, changeset and version checks passed. GitHub Actions run 37386737057 passed every required job, including Codecov patch coverage and the ARC ARM64 image build and smoke test. Disposable-cluster ordering and hardware acceptance remain open. | [PR #51](https://github.com/jyje/pifanctl/pull/51) |

| Event admission follow-up | Publish cluster scoped CR Events in default with a create-only Role. Event admission/RBAC failures are rate limited and retried without blocking reconciliation. Real API dry-run accepted the corrected Event. Full Python 3.14: 236 tests, 95.69%; Helm lint passed in both input modes. | `6a0f5a5` |

| Worker monitoring follow-up | Headless worker Service and optional ServiceMonitor in managed/reuse modes. Unready endpoints remain visible for failsafe metrics. Label/port discovery regression checks and migration guidance added. Full Python 3.14: 239 tests, 95.69%; monitoring-enabled Helm lint passed. | `d1a1409` |

| Operator replacement follow-up | Default to one operator and use Recreate so leader-only readiness cannot deadlock a surge update. Full Python 3.14: 239 tests, 95.69%; chart regression/lint passed. CI passed all nine jobs. Multi-replica readiness remains a follow-up. | `837b3d5` |
| Release acceptance manual and bounded thermal trial | Filled the live inventory with verified cluster data and marked unobserved hardware facts as not recorded. Ran capped 1, 2, and 3 vCPU loads on `raspi-41` with the shared fan enabled, a 65°C cutoff, and fresh Prometheus monitoring; peak was 55.1°C on `raspi-51`, with a 47.85% Fan status request. The target node peaked at 50.147°C, and neither load attribution nor stabilization was proven. The delayed five-minute no-load observation also did not stabilize. Added raw samples, measured response graph, configured-curve hypothesis, and regenerated PDF. Image `887f6f1-py312` (digest `sha256:525ef9f01f7bd4d5af5ac4d4014d9f0320187628c41cd2eacd028d5fbb896cf5`) remained deployed. Physical rotation confirmation, fan-stop recovery, PWM waveform, Pi 5, fault, rollback, and fleet-load gates remain open. | Pending |
| Alpha.2 shared-fan response follow-up | Archived the exact live MicroK8s baseline, ran bounded 1 and 2 vCPU loads on hottest member `raspi-51`, stopped at the 60°C stage gate with a 61.15°C sampled overshoot, verified no-load cooldown and temporary-Pod cleanup, and recorded 22 Prometheus observations with an SVG/PNG graph in the updated manual and PDF. Argo CD remained Synced/Healthy; the controller and four agents remained Ready. This is not v1 CRD or physical PWM/RPM acceptance. | `b6b9aed` |
| Alpha.3 CRD runtime probe | Built a Python 3.12 ARM64 issue image from the PR head, installed the v1 operator chart in an isolated namespace, verified CRD establishment/defaulting/admission and expected missing-node statuses, and confirmed Argo CD Synced/Healthy. An alpha.2 image rejected the API-defaulted alpha.3 hysteresis field, exposing the image/CRD version boundary. Removed the temporary CRs, Application, and namespace; no worker or GPIO was used. The production alpha.2 controller remains the sole GPIO18 writer on `raspi-40`. | [Workflow 37429082468](https://github.com/jyje/pifanctl/actions/runs/37429082468) |
| Live staged single-writer handoff | Merged cluster PRs #144, #145, and #146. Installed the alpha.3 operator with no CRs, kept four alpha.2 temperature agents, disabled the legacy controller, and enabled pruning after Argo showed the controller DaemonSet was the only extra resource. Argo is Synced/Healthy; the controller DaemonSet and Pod are gone; v1 operator is Ready; no worker exists. The physical fan's rotation after GPIO18 was left high is awaiting direct confirmation. | [PR #144](https://github.com/jyje/cluster/pull/144), [PR #145](https://github.com/jyje/cluster/pull/145), [PR #146](https://github.com/jyje/cluster/pull/146) |
| Alpha.3 live rack worker | Cluster PR #147 declared the shared GPIO18 fan and four-node CoolingZone. Verified Argo Synced/Healthy, worker Ready on `raspi-40`, fresh telemetry from four members, and closed-loop duty response. An unforced sample showed a 50.7°C zone maximum and 45.96% requested duty. | [PR #147](https://github.com/jyje/cluster/pull/147) |
| Alpha.3 55°C shared-rack response | After the user confirmed normal physical rotation before the run, applied a 1 vCPU capped load on `raspi-51`. Twenty-three composite observations stayed within 54.55–55.65°C for 144 seconds at 50.44% requested duty. Peak was 57.3°C, below the 58°C soft and 62°C hard stops. The load Pod was removed; follow-up confirmed no load Pod, Ready operator/worker, and Ready Fan/CoolingZone. Continuous visual observation during the run, RPM, and electrical waveform were not recorded. The 1°C total-range criterion held for only 75 seconds, so all three stability targets and failure cases remain open. CSV, graph, and refreshed PDF are in `docs/v1/`. | Pending |
| Coverage CI follow-up | PR #43 merged into the still-open PR #41 branch. CI passed Python 3.10-3.14 with 259 tests each, the 90% line gate, branch reporting, workflow/version/Helm checks, ARM64 image smoke test, and authenticated Codecov upload. Baseline: 95.75-95.77% line and 88.2129-89.1635% branch coverage. Codecov's main-branch comparisons and the first main badge publication remain unverified until PR #41 reaches the default branch. | `6dc6bfa` |
| CRD-only CLI contract | Removed standalone control, restricted local YAML to mock, retained operator workers, updated both localized READMEs/runtime manuals and archived v0 instructions. Added rejection/operator-plan tests and a driver-specific image probe that cannot pass on a CLI/import error. 307 tests passed with zero skips; statement coverage 96.29%, branch coverage 89.81%, combined 94.67%. Six nonprivileged ARM64 image checks, actionlint, Helm lint, and changeset validation passed. Evidence: `docs/v1/crd-only-cli-verification.json`. App alpha.4; chart pin and live deployment stay alpha.3 until a separately verified upgrade. CI run `37489633049` passed all five Python versions, coverage, Helm/workflow/version and ARC ARM64 image checks; PR #55 merged at `949bd3a`. | `d4ffd57` |
| Stable topology API and storage migration | Candidate app alpha.5/chart 0.1.0-alpha.4 serves identical v1 and alpha schemas. Four real migration/rollback checks and nineteen dual API checks passed on kind 1.37.0 with the old alpha.3 compatibility operator and missing-node fixtures. 315 local tests passed with zero skips; line 96.29%, branch 89.81%. No live MicroK8s changes. Active hardware/runtime/minimum-version acceptance remains open. | [PR #56](https://github.com/jyje/pifanctl/pull/56), merge `e90892e` |

| Active worker runtime lifecycle | Fourteen checks passed on kind 1.37.0 using alpha.6 candidate code with explicit simulated I/O. Retained the alpha.5 startup failure, prepared the node OS lock-directory target, and kept the legacy host lock while using a direct container mount. 320 full tests and 24 Python 3.10 focused tests passed; statement 96.29%, branch 89.81%. All lab CRs/workers finalized without force. Live MicroK8s unchanged and Ready. Argo ordering, minimum version, physical acceptance and live migration remain open. | [PR #57](https://github.com/jyje/pifanctl/pull/57), merge `74e9694` |

- Runtime PR #57 CI `37495486653` passed all five Python versions, Codecov/coverage, Helm, workflows, version checks and ARC ARM64 image checks. Main CI `37495865042`, image publication `37495865690`, chart publication `37495865097` and main coverage badge publication passed after merge.

| Minimum Kubernetes compatibility and live read-only preflight | Kubernetes 1.30.0 passed nineteen v1/alpha API checks and fourteen active runtime checks with simulated I/O. The alpha.6 Python 3.12 compatibility image read four live Nodes and the existing Fan/CoolingZone with TLS verification enabled and produced a plan without issues. Nonprivileged preflight Pod was archived and deleted; active cooling unchanged. Live upgrade/migration/rollback and hardware acceptance remain open. CI `37497748578`, including all Python versions, ARC and Codecov project/patch, passed before merge. | [PR #58](https://github.com/jyje/pifanctl/pull/58), merge `59e995c` |

| Argo CD staged lifecycle and shared CRD retention | Seventeen strict source-aware checks passed on Argo CD 3.5.2/Kubernetes 1.30.0 with explicit simulated I/O. Verified absent-CRD initial installation, two active fans, ownership transfer without worker replacement, cooperative pruning, worker removal before operator deletion and retained CRD UIDs. Chart 0.1.0-alpha.6 adds CRD prune/delete protection; app remains alpha.6. 330 tests passed, statement 96.29%, branch 89.81%. The initial stale-status trial is audited and excluded from acceptance. Live MicroK8s remained alpha.3 during this isolated phase. CI `37502333871` passed all Python/Codecov/ARC checks; main CI `37524631559` and chart publication `37524631324` passed. | [PR #59](https://github.com/jyje/pifanctl/pull/59), merge `e04f73b` |

### Regressions found and fixed

- An initial Argo CD verifier accepted the previous Synced/Healthy/Succeeded status immediately after Helm values changed. Requiring both comparison and operation-result source values and revisions to match the current spec fixed the check. The real stale snapshot is a regression fixture; only the repeated strict trial counts as acceptance.
- The topology example inventory initially treated the new Argo Application envelope as a direct Fan/CoolingZone document. It now extracts and validates every embedded CR instead of skipping the example. The complete suite passed after this fix.

- Initial stable API CI run `37491458686` caught quote reuse in an f-string that Python 3.10/3.11 could not parse. Replaced it with portable string concatenation. Real 3.10.20 and 3.11.13 parsers compiled all 30 application/script files; the full local 315-test suite passed again. Updated-head CI `37491912775` passed all required checks before PR #56 merged at `e90892e`. Main CI `37492287660`, image publication `37492288229`, and chart publication `37492287712` subsequently passed.

- Python 3.10 could not resolve a Typer Context with a None default. Required Context injection fixed the commands; 214 tests passed with 92.53% coverage at that stage.
- Main expanded CI to Python 3.10-3.14 during development. Preserve all five versions and the existing 90% coverage gate, with a regression test.
- Kubernetes client 36 call_api requires response_types_map. Real client/fake HTTP testing exposed the argument issue hidden by the fake adapter.
- Separated operator HTTP snapshot and topology snapshot method names.

## Verification evidence

- [Runtime/RBAC CI](https://github.com/jyje/pifanctl/actions/runs/37123255182): all nine jobs passed, including Python 3.10-3.14 and ARM64.
- [Earlier runtime CI](https://github.com/jyje/pifanctl/actions/runs/37122808616): 228 tests per Python version, 95.72-95.74% coverage.
- Local macOS: Python 3.10-3.14 each passed 228 tests, 95.66-95.68% coverage. After the RBAC change, Python 3.14 again passed 228 tests, 95.66%.
- [Runtime variant CI](https://github.com/jyje/pifanctl/actions/runs/37126362598): all nine jobs passed; local Python 3.14 passed 233 tests with 95.66% coverage.
- kubeconform validates static schemas. It does not establish API admission, CEL, or defaulting behavior. The CRD follow-up above includes real API evidence.
- PR #40 holds the design, CRDs and scenario SVG/PNG files. PR #41 holds the runtime and sequential implementation commits. Review PR #40 first.

## Final source verification

- [CI for 837b3d5](https://github.com/jyje/pifanctl/actions/runs/37165310923): all nine jobs passed.
- [CI for d1a1409](https://github.com/jyje/pifanctl/actions/runs/37165023194): Python 3.10-3.14 each passed 239 tests, 95.75-95.77% coverage; all nine jobs passed.
- English primary artifact policy is recorded in AGENTS.md; Korean illustration guidance moved into illustration-style-ko.md in `e5a1c64`.
- For existing SSA-managed Deployments, clear the old rollingUpdate field when adopting Recreate, as documented in the operator chart manual.

## Coverage CI follow-up: issue #42, implemented and merged into `main`

- [x] Preserve the Python 3.10-3.14 matrix and independently enforce the existing 90% line floor.
- [x] Collect branch-aware XML, JSON and HTML reports and validate per-version artifacts at one tested commit.
- [x] Add a canonical Python 3.14 Codecov upload with informational provider statuses.
- [x] Add successful-main-only, revision-stamped line and branch badge publishing.
- [x] Introduce a validated v1 changeset ledger without adding a Node package manager or replacing app/chart version files.
- [x] Remove the test that asserted historical StepController outputs; retain the bounded step-controller test.
- [x] Run the five-version CI matrix and review the initial branch baseline.
- [x] Verify the first successful main badge publication under `assets/coverage/`.

The coverage baseline is not inferred from prior line-only results. Hardware and
operator safety still need the separate v1 release acceptance work above.

- [PR #43 CI run 37169304903](https://github.com/jyje/pifanctl/actions/runs/37169304903): all five Python matrix reports, the `Coverage quality` gate, version check, chart validation, workflow lint, and ARM64 image smoke test passed. GitHub Actions measured 95.75-95.77% line coverage and 88.2129-89.1635% branch coverage.
- The first canonical OIDC upload returned `Repository not found`. The repository owner configured the `CODECOV_TOKEN` Actions secret; the uploader now uses that secret for main and trusted same-repository PR runs. The authenticated upload was accepted in CI. Upload remains non-blocking.
- [PR #43 CI run 37189547667](https://github.com/jyje/pifanctl/actions/runs/37189547667): all five Python versions passed 259 tests; `Coverage quality`, version, workflow, Helm, ARM64 image and Codecov jobs passed. The canonical report upload was accepted with the repository token. Codecov posted its integration welcome comment. PR #43 merged into PR #41 at `6dc6bfa`.
- Main CI run [37191841522](https://github.com/jyje/pifanctl/actions/runs/37191841522) passed tests, reports and Codecov statuses on merge commit `eb77c0c`, but badge publication failed because the orphan-branch initialization attempted to remove files from an empty index. PR #44 replaced the separate branch with `assets/coverage/` updates on `main`.
- Main CI run [37193265541](https://github.com/jyje/pifanctl/actions/runs/37193265541) passed all required jobs, including Codecov and badge publishing. Commit `38f16a0` publishes badges measured from `99f5027`: 95.7527% line coverage and 88.2129% branch coverage. Codecov `project` and `patch` statuses succeeded on the main merge commit.

### Live migration verification tooling

- Added explicit manual-sync and archived-storage guards, complete inventory
  rewrites, checksum/UID-checked reverse restoration and fresh-snapshot waits.
- Added read-only runtime holds with source-matched Argo success, exact image
  digest, single-worker/credential/host-lock checks and direct worker heartbeat.
  Each member's original Prometheus sample time is checked rather than the
  instant query evaluation timestamp.
- 368 full Python 3.13.2 tests passed without skips; statement coverage 96.29%,
  branch coverage 89.81%. Related Python 3.10 checks: 44 passed.
- Initial stale preflights made no mutations. A later successful storage rewrite
  failed its immediate 20-second published-heartbeat check by 0.385 seconds.
  That report stays failed. CR status publication is throttled to 30 seconds;
  subsequent storage verification waits for a fresh snapshot without loosening
  its age limit, and runtime verification uses direct heartbeat/source clocks.
- Runtime proxy observation initially failed because kubectl's request-timeout
  query reached the worker's exact `/status` route. The read-only observer now
  bounds its subprocess without adding that proxy query. Failed reports remain
  excluded. Candidate and archived-image holds then passed.
- Candidate return and self-heal restoration passed through cluster PR #150 and a further 120.6-second hold. Hardware/thermal/fleet and full v0 topology rollback gates remain open.
- Tooling committed as `b82b509`. Cluster preparation #148, runtime rollback #149 and restoration #150 passed CI and merged. Public evidence, excluded attempts and the updated manual are recorded in the next documentation commit.

- Automatic approval review rejected pushing complete live Kubernetes snapshots
  to GitHub because they expose internal infrastructure identifiers and config.
  Public evidence now contains anonymous measurements and check results only;
  full UID/IP/configuration snapshots remain in the checksum-verified private
  archive. Added a reproducible public projection and privacy regression tests.
- Public projection and private/non-overwriting report guards passed eight
  privacy tests and two overwrite-refusal tests. The complete suite passed
  368 tests; statement/branch coverage remains 96.29%/89.81%.

### Fixed-load thermal acceptance follow-up

Publication of PR #60 and its acceptance PDF was explicitly approved by the
maintainer. Raw infrastructure snapshots remain private.

- [x] Verify the selected member can read its local thermal sensor without
  privilege, host volumes, device access or service account credentials.
  The read-only probe identified a Raspberry Pi 5 Model B Rev 1.0; no RPM input
  was exposed on that selected member. This does not verify actuator hardware.
- [x] Add and test a reusable collector with private, non-overwriting evidence,
  source-aware GitOps checks, complete per-member acquisition clocks, an
  independent node-local temperature cutoff, deadlines and cleanup.
- [x] Run a fixed 250m CPU scenario targeting 50 C: 30-second baseline, at most
  360 seconds of load, then 120 seconds of immediate cooldown. Keep all fan
  and curve settings unchanged. Stop load at 53 C remotely or 55 C locally;
  retain any failed or interrupted attempt.
- [x] Evaluate the original 120-second, 1 C total-span, 5 percentage-point
  duty-span criteria using independent, advancing per-member source clocks.
- [x] Publish the first measured graph and pass/fail result in the acceptance
  manual, anonymous CSV/JSON and visually reviewed 15-page PDF.
- [ ] Complete separately bounded 55 C and 60 C scenarios under the approved
  `v1-3c` policy. Repeat 50 C after any configuration/runtime change that
  invalidates the recorded observation; retain historical legacy verdicts.
- [ ] Recheck CI and merge each reviewable concern; update the acceptance PDF
  without declaring stable v1 until all remaining hardware gates pass.

- Collector verification: 387 full Python 3.13.2 tests and 33 focused Python
  3.10 tests passed. The initial sandbox run could not bind two local HTTP
  servers; the unchanged tests passed with authorized loopback access.
  Failure injection verified Pod cleanup and immediate cooldown after API loss.

- Public thermal projection and reproducible Matplotlib SVG/PNG generation
  preserve every member acquisition clock and original acceptance criteria.
  Nine projection/counter validation tests passed. Final local suite: 396
  passed with zero skips; focused Python 3.10 thermal/evidence suite: 42 passed.

- First 50 C fixed-load attempt completed: 51 source-aware samples, local 55 C
  cutoff after 155.57 seconds, 0.249 vCPU average. Remote peak was 51.8 C,
  duty 35.04%; the 120-second cooldown ended at a recorded 50.15 C maximum.
  Strict stability failed (0 seconds); broader band lasted 50.21 seconds.
  Failed acceptance is preserved. Seven private raw files passed checksums.
- Migration PR #60 merged as `0ad658f`; all PR checks including ARC ARM64 and
  Codecov passed. Main CI `37533007374` succeeded. Collector PR #61 records
  the next concern; completion and release readiness are separate decisions.

### Approved three-degree thermal policy

The maintainer approved the 3 C stability policy after reviewing the original
50 C observations. The active observation interval is target - 1 C through
target + 2 C, inclusive (49-52 C for the 50 C scenario). Maximum total span is
3 C. Duration remains 120 continuous source-clock seconds with at least eight
observations; duty span remains at most 5 percentage points. Sensor freshness,
worker heartbeat, identity checks and independent thermal cutoffs are unchanged.
This approval changes the measurement policy, not the deployed control curve.

- [x] Version the active policy and preserve the original 1 C evaluator as an
  explicit legacy policy. Add fixed-boundary, duration, gap, stale-source and
  original-evidence regression tests.
- [x] Apply the active policy to future collection/publication. Keep the old
  JSON/CSV/figures unchanged and publish a separately named post-hoc reassessment.
- [x] Verify the 50 C record under both policies: original failure and approved
  3 C pass must remain independently reproducible from the same source CSV.
- [x] Update active acceptance guidance, PLAN, report and figures. Preserve
  historical decisions and missing-data limitations for earlier trials.
- [x] Regenerate and visually inspect the 17-page PDF using the PDF skill.
- [x] Run complete/local compatibility tests, commit each concern and create
  [PR #62](https://github.com/jyje/pifanctl/pull/62).
- [x] Verify source-policy CI `37545369879` on `915c87c`: Python 3.10-3.14,
  chart/version/workflow checks, ARC ARM64 image and Codecov project/patch all
  passed. The final cover-only rerun and merge state are tracked in PR #62;
  clean-main synchronization is verified in the final handoff report.

- Policy verification: 408 full tests and 54 focused Python 3.10 tests passed.
  New and original verdicts are separately reproducible. The reassessment CSV
  is byte-identical to the original; original JSON, SVG and PNG also remain
  unchanged. Section 16 and its figure were visually inspected, along with
  the updated guidance, historical verdict and release-decision pages.

- Added a duration-boundary regression: rounding a 119.999-second interval
  to 120 seconds must not certify the approved policy. Active acceptance
  compares the unrounded duration; original legacy verdicts remain unchanged.

- Final duration-boundary verification: 409 complete tests and 55 focused
  Python 3.10 tests passed without skips. The approved 50 C verdict remains
  140.24 seconds; only display values are rounded.

### Remaining acceptance campaign (2026-10-07)

- [x] Collect fresh 55 C fixed-load trials with complete member acquisition
  clocks, independent local cutoff, unchanged fan settings and immediate cooldown.
- [x] Review the 55 C traces before selecting a separately bounded 60 C trial.
  Preserve failed attempts and actual load execution evidence.
- [x] Measure the disposable runtime lab at declared resource sizes (1/4/16 fans, 4/16/64 zones on one actuator). Separate
  measured API/status behavior from simulated sensor/GPIO and real hardware.
- [x] Exercise recoverable software faults in the disposable lab and record
  failure detection, failsafe commands, recovery and cooperative cleanup.
- [x] Supplement anonymized CSV/JSON/figures and the visually inspected 26-page acceptance PDF. Keep
  electrical PWM, RPM, power-loss and untested hardware gates explicitly open.
- [x] Run the full suite and compatibility checks and commit each concern.
- [x] Publish [PR #63](https://github.com/jyje/pifanctl/pull/63) and verify source/evidence CI on `04bc71d`. Judge release readiness from all required gates.

- Resource-scale campaign: ten lifecycle checks passed. Twelve status samples
  per stage; all fixture finalizers and workers cooperatively released. At
  16 fans / 64 zones, operator mean 0.0193 vCPU / 75.48 MiB sampled RSS and
  worker 0.00393 vCPU / 39.25 MiB; 117 CR API requests include the observer.
  This does not close distributed fleet or actual Prometheus load acceptance.
- HTTP fault campaign: nine normal/fault/recovery checks observed full-duty
  failsafe and fresh recovery. The first abrupt-stop attempt was ineffective
  inside the PID namespace; two harness runs also timed out on source fixture
  cleanup. Both failed reports are retained. The corrected ancestor-PID stop
  and SIGTERM-capable source fixture passed the separate three-check retry
  including cleanup. This is simulated GPIO evidence, not physical safety.
- Read-only actuator inventory now records Pi 4 Model B Rev 1.5 (d03115). No
  exposed tachometer input was found; electrical PWM, RPM and fan/supply model
  remain unmeasured. No production reboot, network cut or power loss occurred.

- Completed 60 C collection: eighty source-aware samples, 360.06-second load,
  0.999 vCPU mean, local peak 61.15 C, remote peak 58.4 C. No qualifying
  interval; last immediate cooldown maximum 45.75 C. Thermal gate remains open.
- Existing production fleet measured read-only: twelve samples over 81.02
  seconds with real Prometheus, one operator/worker/fan and four members.
  Worker mean 0.02291 vCPU / 38.19 MiB sampled RSS; temperature-query p95
  140.06 ms including kubectl and proxy. No broader capacity contract claimed.

- Final local regression: 427 passed, zero skips, Python 3.13.2; statement
  coverage 96.29%, branch 89.81%. Python 3.10 focused acceptance checks: 72
  passed. Version and eight pending changesets validated.
- All four load Pods were deleted and immediate cooldown verified. Live
  postflight confirmed source-matched Synced/Healthy, Ready CRs, the same
  worker Pod/container and topology identities, and no legacy controller.
  The lab operator and all simulated source fixtures were removed; CRDs retained.
- PDF now contains 26 pages. Cover and new pages 18-26 visually inspected;
  original evidence and original policy verdicts remain unchanged.

- New generated SVG trailing spaces and CSV line endings were normalized.
  Measurement rows are unchanged, original evidence untouched, and all four
  new verdicts reproduce exactly. Explicit legacy reassessment preserves the
  original CSV line ending. Final full/compatibility suites: 427 / 72 passed.

- PR CI run `37550806713` passed on `04bc71d`: Python 3.10-3.14,
  chart/version/workflows, coverage quality, authenticated Codecov upload,
  Codecov project/patch and ARC ARM64 build/smoke checks. The final CI-record
  documentation rerun, merge and clean-main synchronization are tracked in
  PR #63 and the final handoff; stable release gates remain open.


### Practical verification closeout approved (2026-10-07)

- [x] Record Raspberry Pi 4 Model B Rev 1.5 as the shared-fan actuator and Raspberry Pi 5 Model B Rev 1.0 as the observed CPU-load/temperature member. Pi 5 actuator behavior remains unverified.
- [x] Preserve all thermal verdicts: CPU load raised temperature, but the new 55 C/60 C trials did not establish the prescribed 120-second plateau. Cleanup and cooldown passed.
- [x] Accept the observed deployment scope for release preparation, with explicit maintainer approval to supplement remaining measurements later. Section 23 of the manual supersedes earlier blanket release-blocking decisions.
- [x] Track deferred thermal characterization, electrical/RPM measurements, physical failures, Pi 5 actuation, expanded rollback and distributed capacity in [issue #64](https://github.com/jyje/pifanctl/issues/64).
- [ ] Carry the verified scope and limitations into the stable app/chart release proposal. No stable tag or version bump is part of this acceptance PR.


### Stable release proposal preparation

- [x] Prepare independent app 1.0.0 and operator chart 1.0.0 version changes.
- [x] Consume eight pending changesets into archived release provenance and a consolidated CHANGELOG.md, without releasing the legacy chart.
- [x] Record verified Pi 4 actuator/Pi 5 member roles, deferred physical/thermal scenarios and Python 3.12 live versus Python 3.14 default-image boundary in release notes.
- [x] Publish [release proposal PR #65](https://github.com/jyje/pifanctl/pull/65): 427 regression tests passed, Helm lint/render and version validation passed, eight archived changesets validated and pending ledger empty. Prepared release commit: `1162363`.
- [ ] Verify proposal CI and candidate image availability/runtime preflight before production adoption.
- [ ] Publish stable artifacts and verify immutable tags, image/chart metadata and deployment rollback readiness.
