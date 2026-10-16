---
"pifanctl": patch
"pifanctl-operator": patch
---
Dependency(client): move to the kubernetes Python client 37

Client 37 split the old `ApiClient.call_api` into serialize, send and deserialize steps,
so the cluster adapter now calls `param_serialize`, `call_api` and `response_deserialize`
in that order. Request bodies, timeouts, error translation and strict TLS handling are
unchanged. The dependency update failed in CI on its own because of this API change.
App and operator chart advance together to 1.5.1.
