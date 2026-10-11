---
"pifanctl": minor
"pifanctl-operator": minor
---
Security(chart): add an opt-in egress NetworkPolicy for hardware workers

Set `networkPolicy.workerEgress.enabled` to limit worker egress to cluster DNS and the
Prometheus endpoint. It is off by default because the allowed destination must match the
`telemetry.prometheusURL` of every CoolingZone. A wrong selector blocks telemetry and
workers request failsafe duty, so verify it on one Node first. Pod hardening that depends
on removing `privileged` is tracked in issue 86 and is not part of this change. App and
operator chart advance together to 1.4.0.
