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

A stable v1.0.0 release requires the remaining hardware and failure acceptance
gates below. Local and CI results alone do not establish electrical cooling safety.

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
- API: `pifanctl.jyje.online/v1alpha1`, cluster scoped Fan and CoolingZone
- Diagrams: shared fans and one fan per board, each with normal, hot, missing-data, and expired-heartbeat scenarios in English and Korean locale files

## Pending checklist


Stages 01-08 have completed implementation, mock verification, sequential commits,
and PR submission, so their pending entries have been removed. Release acceptance
checks remain below. Live trial steps and results are tracked privately.

## Remaining release acceptance gates

### v1 packaging and release preparation

- [x] Set the v1 product contract: CRDs are required, standalone fan control is out of scope, and one operator chart owns the runtime.
- [x] Add `extraResources` to the operator chart so the GitOps Application can declare its `Fan` and `CoolingZone` instances.
- [x] Keep app and chart version checks independent and publish only the supported operator chart from the v1 chart workflow.
- [x] Align primary v1 docs with CRD-only topology and the single-chart packaging model.
- [x] Remove ConfigMap topology selection and `--configmap` from the operator chart and CLI interface.
- [ ] Confirm whether legacy local hardware commands remain available in the v1 application package; remove them from the v1 CLI if they conflict with the CRD-only support contract.
- [ ] Update the `jyje/cluster` Argo CD Application to the operator chart and declare the rack topology in `extraResources`.
- [ ] Test CRD establishment, custom-resource admission, and Argo CD ordering on a disposable Kubernetes cluster.
- [ ] Promote the CRD API to its stable version and test migration of alpha resources before stable `1.0.0`.
- [ ] Complete the hardware, failure, migration/rollback, and fleet-scale acceptance gates below.
- [ ] Release app `1.0.0` and operator chart `1.0.0` after all applicable gates pass; keep later app/chart versions independent.

- [x] Merge design PR #40 and implementation PR #41 into `main` in dependency order.
- [x] Verify the first successful main line and branch badge publication under `assets/coverage/`.
- [ ] Measure real Pi 4 GPIO and Pi 5 sysfs wiring, channel, initialization and shutdown PWM behavior.
- [ ] Stabilize controlled load tests at 50°C, 55°C, and 60°C, record duty and RPM, and measure immediate no-load cooldown with a conservative stop limit below 65°C.
- [ ] Measure fan behavior during process kill, Node reboot, power loss, and network partition.
- [ ] Complete supported hardware migration and rollback acceptance across the documented configurations.
- [ ] Measure status, Prometheus, and API load at the supported fleet size.
- [x] Document electrical fail-open limits and independent fan power requirements. Hardware-specific measurements remain open above.

The repeatable procedures, acceptance criteria, current MicroK8s baseline,
evidence form, and release decision record are in the [v1 release acceptance
field manual](docs/v1/release-acceptance.md) and its [PDF](docs/v1/release-acceptance.pdf).
The isolated trial now runs a Python 3.12 image built from current `main`
(`887f6f1-py312`) because the cluster uses the documented legacy-CA compatibility
path. Argo CD is Synced/Healthy and the Fan/Zone report Ready. Physical rotation
confirmation after this upgrade and all hardware/failure acceptance gates remain
open. A bounded load trial on `raspi-41` used 1, 2, and 3 vCPU for 120-150 seconds
with the shared fan active and a 65°C abort limit. The hottest reading was a
transient 55.1°C on `raspi-51`; the loaded node peaked at 50.147°C, so load
causality and stabilization were not established. A delayed five-minute no-load
interval also did not show a stable plateau. Timestamped samples and measured
and hypothesis plots are in `docs/v1/thermal-load-observations.csv` and
`docs/v1/figures/`. Physical fan-stop, rotation, and waveform checks remain open.
On 2026-10-06, a separate remote response check used the live alpha.2 shared-fan
deployment: an 85-second 1 vCPU load peaked at 58.95°C, then a 2 vCPU stage was
stopped after a 15-second poll observed 61.15°C. Requested duty peaked at 58.14%
in the first stage and was 55.06% at the stop sample. The hottest node returned
to 46.85°C by the last sample of a three-minute no-load observation. The
controller and four node telemetry series remained healthy, and temporary Pods
were removed. This is not v1 CRD runtime, electrical PWM/RPM, physical rotation,
or stable-temperature acceptance. See the [follow-up record](docs/v1/release-acceptance.md#7-2026-10-06-live-shared-fan-follow-up),
its [CSV](docs/v1/thermal-load-observations-2026-10-06.csv), and [plot](docs/v1/figures/thermal-live-2026-10-06.png).

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
| Coverage CI follow-up | PR #43 merged into the still-open PR #41 branch. CI passed Python 3.10-3.14 with 259 tests each, the 90% line gate, branch reporting, workflow/version/Helm checks, ARM64 image smoke test, and authenticated Codecov upload. Baseline: 95.75-95.77% line and 88.2129-89.1635% branch coverage. Codecov's main-branch comparisons and the first main badge publication remain unverified until PR #41 reaches the default branch. | `6dc6bfa` |

### Regressions found and fixed

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
