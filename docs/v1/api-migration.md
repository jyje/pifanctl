# CRD API migration and rollback

The candidate API serves `pifanctl.jyje.online/v1` and `v1alpha1`. `v1` is the storage version. Both versions have identical schemas, defaults, CEL validations, status subresources and printer columns. Kubernetes `None` conversion changes only the API version. The CLI accepts alpha YAML and emits canonical v1 resources; existing identities, hardware placement and worker plans are preserved.

API stability does not certify hardware or make the alpha application a stable release. The live MicroK8s deployment still uses its earlier alpha CRDs and alpha.3 runtime until the candidate image and deployment are verified. The app candidate is alpha.5 and the operator chart is 0.1.0-alpha.4.

## Operator upgrade order

1. Archive the current CRDs, every Fan/CoolingZone, GitOps values, image digests and channel inventory. Preserve resource UIDs, ownership annotations, finalizers and status. Freeze topology edits during storage migration.
2. Apply the dual-version CRDs explicitly. Helm does not upgrade existing CRDs. Wait for Established and verify both discovery endpoints.
3. Existing alpha operators can continue using the served alpha endpoint. Deploy the reviewed new operator image, preserving its installation ID, namespace, lease and single-writer ownership.
4. Rewrite every stored custom resource through the v1 API using current resourceVersion and unchanged spec. Retry conflicts from a fresh read; abort on changed identity or topology. A read or a served-version change alone does not rewrite stored data.
5. After successful rewrites and a complete inventory check, remove v1alpha1 from each CRD's status.storedVersions. Keep the alpha endpoint served for compatibility. Never patch storedVersions first or force-remove fan finalizers.
6. Change GitOps instance apiVersion values to v1 and verify readiness, plan hashes, duty and fresh telemetry. Retain the rollback archive through release acceptance.

## Reverse rollback

Keep both versions served and make v1alpha1 the storage version. Rewrite all resources through the alpha endpoint, verify preserved identity/spec/status and complete inventory, then set storedVersions to v1alpha1. Restore the archived alpha-only CRD spec only after this rewrite. Restore a compatible operator image and preserve one hardware writer. Do not delete CRDs: that deletes the custom resources.

## Reproducible isolated verification

`scripts/verify_storage_migration.py` intentionally refuses contexts other than kind-pifanctl-release. It requires an original alpha-only baseline, writes an archive before mutations, tests both read endpoints, rewrites every resource to v1, verifies storage history, and rewrites back before restoring the original CRD specs. It is a verification harness, not an automatic production migrator.

```sh
python scripts/verify_storage_migration.py \
  --kubeconfig /path/to/isolated-kind.config \
  --archive /path/to/new-archive-directory \
  --report /path/to/migration-report.json
```

The [migration report](storage-migration-verification.json) records promotion and reverse rollback of the two real release fixtures on Kubernetes 1.37.0, preserving UID, generation, spec, ownership metadata, finalizers and status. The [stable API report](stable-api-verification.json) records nineteen admission/defaulting/reconciliation/finalizer checks, including CEL rejection through both served endpoints after reinstalling the dual-version schemas. The operator remained the alpha.3 compatibility image; missing-node fixtures created no hardware worker. These checks do not prove active-worker migration, Argo CD ordering, minimum-version support, electrical behavior or production rollback.

Reference: [Kubernetes custom resource versioning and storage upgrades](https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definition-versioning/).
