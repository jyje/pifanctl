---
"pifanctl": minor
"pifanctl-operator": minor
---
Feature(status): expose per-node temperatures in CoolingZone status

`CoolingZone.status.nodeTemperatures` now lists every resolved member with its
temperature, sample time, `ready` flag and a `Fresh`, `Stale`, `Missing` or
`Unavailable` reason, so the hottest node is visible from `kubectl get -o yaml`
and `kubectl describe` without a Prometheus query. The zone maximum, missing node
names, the Ready condition and failsafe behavior are unchanged. Apply the additive
CRD update before the new operator image. App and operator chart advance together
to 1.3.0.
