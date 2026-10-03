# v2 design resources

**Proposal only.** These files define an API and render topology examples. They
do not implement an operator, config reload, grouped fan control, or a new CLI.
The released application and `charts/pifanctl` remain at their current versions.
Do not deploy these resources as an upgrade to a running cooling installation.

Read the [design](../../docs/v2/README.md) or [한국어 설계](../../docs/v2/README-ko.md).

| Directory | Contents |
| --- | --- |
| `crds/` | Cluster scoped `Fan` and `CoolingZone`, first API version `v1alpha1` |
| `examples/` | Two four-node racks, per-node fans, two fans on one node, standalone, sysfs, ConfigMap, Helm values |
| `helm/` | Resource rendering chart, version `0.0.0`, no workloads or CRD lifecycle management |
| `operator/` | Proposed service account and RBAC, no Deployment or invented image |

## Render locally

These commands work today and make no changes to a cluster:

```sh
helm lint design/v2/helm -f design/v2/examples/helm-values.yaml
helm template topology design/v2/helm -n pifanctl-system \
  -f design/v2/examples/helm-values.yaml
helm template topology design/v2/helm -n pifanctl-system \
  -f design/v2/examples/helm-values.yaml --set mode=configMap
```

The chart requires all referenced fans in the same values file. For independently
managed fans and zones, use the plain manifests. It checks JSON Schema shapes and
fan references; it does not execute Kubernetes CEL or validate hardware claims.

## API review in a disposable cluster

The proposed minimum is Kubernetes 1.30. CRDs use structural schemas, defaults,
CEL field validation and a `/status` subresource. API server validation still
needs to be exercised before implementation; local rendering is not that check.

```sh
# Run only against an explicitly selected disposable cluster.
kubectl --context <review-cluster> apply -f design/v2/crds/
kubectl --context <review-cluster> wait --for=condition=Established \
  crd/fans.pifanctl.jyje.online crd/coolingzones.pifanctl.jyje.online
kubectl --context <review-cluster> apply --dry-run=server --validate=strict \
  -f design/v2/examples/two-racks.yaml
```

CRDs alone do not turn fans. No live cluster is required to review this proposal.
RBAC is a starting permission inventory, not evidence of a running operator.
