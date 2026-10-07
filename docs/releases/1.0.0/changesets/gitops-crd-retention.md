---
"pifanctl-operator": patch
---

Fix(chart): retain shared CRDs during Argo CD prune and application deletion

Prevent automatic deletion of the cluster-wide Fan and CoolingZone definitions
when the operator Application is pruned or removed. Document background CR
pruning and staged retirement while the operator remains available. Add an
isolated Argo CD lifecycle verifier for initial admission, active claims,
cooperative pruning and retained API definitions.
