---
"pifanctl": patch
"pifanctl-operator": patch
---
Fix(diagnostics): report strict TLS rejection of the cluster CA with a typed reason

When Python 3.13+ strict X.509 verification rejects the Kubernetes API certificate
chain, for example a CA without Key Usage, the CLI and the operator log now name the
OpenSSL finding with the reason `StrictTLSCertificateRejected` and point to
docs/v1/cluster-ca.md instead of a generic transport failure. TLS verification, the
strict flag and hostname checks are unchanged and are never relaxed. The failure
cannot be written to a CR status because the API is unreachable at that point.
App and operator chart advance together to 1.2.2.
