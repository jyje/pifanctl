---
"pifanctl": patch
"pifanctl-operator": patch
---
Fix(operator): keep /readyz ready while a reconcile pass runs

The operator cleared its readiness at the start of every pass, so `/readyz` answered 503 for as
long as a pass ran and the kubelet logged `Unhealthy` events. A leader that reconciled within the
last 30 seconds now stays ready during a pass. Readiness is still cleared when leadership is lost
or a pass fails, goes stale after 30 seconds without a successful pass, and is not set before the
first successful pass. Worker heartbeats, failsafe behavior and status writes are unchanged.
App and operator chart advance together to 1.5.2.
