# Argo CD staged lifecycle verification

## Result and acceptance boundary

Seventeen checks passed on real Argo CD 3.5.2 and Kubernetes 1.30.0 from
17:04:14 to 17:06:53 UTC on 2026-10-06. The candidate chart was
0.1.0-alpha.6 at commit `932745c`; the unchanged alpha.6 runtime used explicit
GPIO/thermal simulations. This is GitOps/runtime software evidence, not
physical waveform, RPM, cooling stability, hardware fault or live migration
acceptance. MicroK8s was unchanged.

## Staged procedure and observed evidence

| Step | Action | Observed result |
| --- | --- | --- |
| 01 | Start without either pifanctl CRD. | Both definitions were absent at verifier preflight. |
| 02 | Argo CD renders the pinned chart and both Fans plus a CoolingZone from `extraResources`. | CRDs established before instance admission; Application Synced/Healthy; all instance CRs Ready; one credential-free, Node-bound worker requested 47.5% at synthetic 55 C. |
| 03 | Remove the first Fan and its zone reference from desired values. | Background prune finalized the Fan; its simulated driver stopped; the remaining fan continued regulating in the same worker Pod. |
| 04 | Set desired `extraResources: []` while retaining the operator. | All instance finalizers completed; worker Pod disappeared before the Ready operator was removed. |
| 05 | Delete the operator Application after retirement. | Application and operator disappeared; both shared CRDs stayed Established with their original UIDs. |

The [raw verification](gitops-lifecycle-verification.json) contains checks,
source-matched Application snapshots, worker states, CRD establishment and
retained identities. The [worker log](gitops-lifecycle-worker-log.txt) records
simulated driver activity. Fan prune synchronization took 64.82 seconds;
complete instance prune synchronization took 78.73 seconds in this lab.
These timings include reconciliation and ConfigMap projection, not a guaranteed
physical failsafe latency.

## Supported GitOps configuration

Use [the Application example](../../design/v1/examples/argocd.yaml), replacing
Node names and verifying physical wiring. Pin a published chart tag or full
commit. `PrunePropagationPolicy=background` follows this alpha's supported
release-acknowledgement path; `PruneLast=true` applies desired changes before
pruning retired resources. Directly deleting a CR still present in GitOps values
can cause self-heal to recreate it.

For full retirement, remove desired instances first and include any CLI-created
CRs in the installation inventory. Keep the operator available until all claims
and workers finish release. Then remove its Application. An unreachable worker
must leave release pending; never clear finalizers to make a test pass.

The chart adds `Prune=false,Delete=false` only to the shared CRDs. Helm already
retains definitions in `crds/`; these annotations also prevent Argo CD from
automatically deleting the cluster-wide API. CRD deletion is not a migration or
rollback procedure. See the official [sync options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
and [Application deletion](https://argo-cd.readthedocs.io/en/stable/user-guide/app_deletion/)
documentation for the underlying controls.

## Verifier regression and repeated trial

The first trial observed normal retirement and retention, but its status
predicate could accept a previous successful sync immediately after values
changed. It is excluded from acceptance. The
[stale-status audit](gitops-stale-status-audit.json) records the mismatched source
counts. The real snapshot is retained as
`tests/fixtures/argocd-stale-success.json`.

The corrected predicate requires both `status.sync.comparedTo.source` and
`status.operationState.syncResult.source`, plus both resolved revisions, to
match the current source spec before accepting Synced/Healthy/Succeeded. A new
complete trial from empty CRDs passed. Unit tests reject stale comparison,
stale operation source, wrong revision, incomplete status and error conditions.

The new Application example also exposed an older test's assumption that every
design YAML was a direct topology document. Its validator now extracts and
checks the embedded `extraResources`; the example is not skipped.

## Reproduction and supporting checks

Install Argo CD 3.5.2 in the isolated kind context using its pinned
[official manifest](https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.2/manifests/install.yaml).
Prepare the Node lock directory and load the explicit lab image using the
[runtime lab instructions](../../tests/runtime_lab/README.md). Initially both
pifanctl CRDs and the `pifanctl-release` Application must be absent. Never reset
production CRDs to reproduce this isolated test.

Run `scripts/verify_gitops_lifecycle.py` with `--kubeconfig`, an immutable
`--revision`, `--report`, `--logs` and `--archive-dir`. It leaves failure state
available for diagnosis. It never forces finalizers or uninstalls a controller
while a claim still requires acknowledgement.

The full local Python 3.13.2 suite passed 330 tests without skips; statement
coverage was 96.29%, branch coverage 89.81%. See
[local verification](gitops-local-verification.json). Remote PR CI and merge are
tracked separately. Production upgrade/rollback, thermal stability, electrical
measurements, hardware failures and fleet load remain in [PLAN.md](../../PLAN.md).
