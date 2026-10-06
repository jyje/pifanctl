# v1 design resources

These files describe the v1 alpha topology API and render examples. The actual
operator chart lives in [charts/pifanctl-operator](../../charts/pifanctl-operator).
See the [runtime manual](../../docs/v1/runtime.md) before installing an alpha.
Hardware and API server acceptance remain separate gates.

Read the [design](../../docs/v1/README.md) or [Korean design](../../docs/v1/README-ko.md).

| Directory | Contents |
| --- | --- |
| `crds/` | Cluster scoped `Fan` and `CoolingZone`, `v1` storage and served `v1alpha1` compatibility |
| `examples/` | Two four-node racks, per-node fans, two fans on one node, standalone, sysfs, ConfigMap, Helm values |
| `helm/` | Resource rendering chart, version `0.0.0`, no workloads or CRD lifecycle management |
| `operator/` | Proposed service account and RBAC, no Deployment or invented image |

## Render locally

These commands work today and make no changes to a cluster:

```sh
helm lint design/v1/helm -f design/v1/examples/helm-values.yaml
helm template topology design/v1/helm -n pifanctl-system \
  -f design/v1/examples/helm-values.yaml
helm template topology design/v1/helm -n pifanctl-system \
  -f design/v1/examples/helm-values.yaml --set mode=configMap
```

The chart requires all referenced fans in the same values file. For independently
managed fans and zones, use the plain manifests. It checks JSON Schema shapes and
fan references; it does not execute Kubernetes CEL or validate hardware claims.

## API review in a disposable cluster

The declared API baseline is Kubernetes 1.30. Real API and simulated-I/O worker lifecycle verification passed on Kubernetes 1.30.0 and 1.37.0; see the [minimum-version record](../../docs/v1/minimum-kubernetes.md). Hardware and production migration acceptance remain separate release gates. See the [storage migration and rollback procedure](../../docs/v1/api-migration.md). CRDs use structural schemas, defaults,
CEL field validation and a `/status` subresource. API server validation still
needs to be exercised before stable release; local rendering is not that check.

```sh
# Run only against an explicitly selected disposable cluster.
kubectl --context <review-cluster> apply -f design/v1/crds/
kubectl --context <review-cluster> wait --for=condition=Established \
  crd/fans.pifanctl.jyje.online crd/coolingzones.pifanctl.jyje.online
kubectl --context <review-cluster> apply --dry-run=server --validate=strict \
  -f design/v1/examples/two-racks.yaml
```

CRDs alone do not turn fans. No live cluster is required to review this proposal.
RBAC is a starting permission inventory, not evidence of a running operator.
