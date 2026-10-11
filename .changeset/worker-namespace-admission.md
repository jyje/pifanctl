---
"pifanctl": minor
"pifanctl-operator": minor
---
Security(chart): add an optional worker namespace and a worker admission policy

`workerNamespace` moves hardware workers, plans, the worker Service and agents into a
separate namespace so the release namespace holds only the operator and can be restricted.
The operator Role there shrinks to Leases and Events. `workerAdmission.enabled` adds a
ValidatingAdmissionPolicy that limits what the operator can create in the worker namespace
to the known worker shape. Both are off by default. Existing installations are unchanged
until they set a value, and old worker Deployments must be removed by hand after a move.
Verified in a disposable Kubernetes 1.30 cluster with the real operator code; not verified
on the live rack. Tracked in issue 86. App and operator chart advance together to 1.5.0.
