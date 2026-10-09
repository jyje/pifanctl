# Cluster CA compatibility

Python 3.14 is the only supported pifanctl runtime. Certificate compatibility is
an infrastructure requirement. Runtime downgrades and relaxed TLS verification
do not correct a malformed CA.

## Reproduced finding

A read-only check against the current MicroK8s API on 2026-10-09 produced:

```text
runtime=3.14 strict=True hostname_check=True
strict_tls=FAIL 92 CA cert does not include key usage extension
```

The configured CA has Subject Key Identifier, Authority Key Identifier and
critical Basic Constraints (`CA:TRUE`), but no Key Usage extension. The official
Kubernetes client 36.0.3 with urllib3 2.8.0 also failed a read-only `/version`
request on Python 3.14. All four cluster nodes remained Ready during inspection.
No certificates or running workloads were changed by this investigation.
The infrastructure work is tracked in [cluster issue #157](https://github.com/jyje/cluster/issues/157).

Python and urllib3 enable strict X.509 validation on Python 3.13 and later.
The observed rejection is a certificate structure defect exposed by those
checks. Correcting this first failure does not prove the entire chain is valid;
check leaf/intermediate extensions, validity, identity and signing relationships
as part of acceptance. A generated test-only CA/server chain passes strict
verification with critical signing Key Usage and fails with that extension
omitted. This regression proves the diagnosed property without changing the
production CA or establishing acceptance for its complete chain.

## Required certificate properties

A CA used to sign certificates needs critical Basic Constraints with `CA:TRUE`
and an appropriate Key Usage extension permitting certificate signing
(`keyCertSign`; include `cRLSign` if that CA signs CRLs). Check the installed
MicroK8s certificate generation profile, leaf server certificate SANs, Authority
Key Identifier and issuer chain before generating replacement certificates.

Inspect public certificate extensions locally:

```sh
openssl x509 -in ca.crt -noout -text
openssl verify -x509_strict -CAfile ca.crt server.crt
```

Keep CA private keys, credentials, complete kubeconfigs and backups outside
public Git repositories. A clean offline chain check is necessary but does not
prove the live API serves that chain or every consumer received the trust bundle.

## Maintenance sequence

1. Inventory the current MicroK8s version, control-plane roles, signing profile,
   leaf certificates and trust consumers: node credentials, kubeconfigs, Argo
   CD, service-account CA mounts, webhooks and API clients.
2. Archive private certificate/key state, client configuration and datastore
   backup. Define restoration commands and a maintenance window. Preserve the
   installed fan controller and an independent cooling recovery method.
3. Verify a compliant candidate chain offline. Prefer a supported MicroK8s
   maintenance procedure. A same-key CA reissue is only a candidate after issuer,
   AKI/SKI, existing leaf compatibility and installed-version behavior are tested;
   do not assume it is a supported shortcut.
4. Review the exact cluster operation before execution. MicroK8s documents that
   replacing the CA affects credentials and auxiliary certificates, should not
   be performed with running workloads, and requires multi-node leave/rejoin to
   propagate replacement certificates. A CA refresh is not merely a leaf-server
   certificate refresh.
5. During the maintenance window, deploy the verified CA/chain and distribute
   trust consistently. Follow the installed MicroK8s procedure for affected
   nodes and credentials; retain the recovery archive until acceptance passes.
6. Confirm Python 3.14 strict TLS and the actual Kubernetes client both succeed
   from outside the cluster and a representative pod with mounted cluster CA.
   Verify service-account authentication and required Fan/CoolingZone/Node APIs.
7. Update the cluster GitOps image to the supported Python 3.14 artifact and
   verify Argo revision, operator/agents/workers, fresh telemetry, Fan readiness,
   RPM feedback and preserved thermal regulation. Enable a PWM probe only after
   its independent wiring acceptance.
8. Exercise the reviewed rollback if trust propagation or runtime acceptance
   fails. MicroK8s offers undo for its last certificate operation, but that alone
   does not restore all separately updated kubeconfigs, node state or consumers.

Do not set `verify_ssl=False`, clear `VERIFY_X509_STRICT`, patch urllib3 defaults
or use `-py312` as the new supported deployment. Historical images remain
available for the existing rollback archive; this change does not delete them.

## Acceptance checklist

- [x] Reproduce Python 3.14 strict rejection and inspect the CA extensions.
- [x] Confirm the actual Python 3.14 Kubernetes client also fails.
- [ ] Archive infrastructure state and review a compliant candidate chain.
- [ ] Perform cluster certificate maintenance and verify trust propagation.
- [ ] Pass strict external and in-pod API checks with Python 3.14.
- [ ] Switch GitOps and verify the complete pifanctl runtime.

References: [Python SSL strict verification](https://docs.python.org/3.14/library/ssl.html),
[urllib3 context implementation](https://github.com/urllib3/urllib3/blob/main/src/urllib3/util/ssl_.py),
and [MicroK8s certificate maintenance](https://canonical.com/microk8s/docs/command-reference#microk8s-refresh-certs-version-119).
