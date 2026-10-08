---
"pifanctl": minor
"pifanctl-operator": minor
---
Feature(feedback): optional Pi 4 tachometer feedback

Add opt-in Fan tachometer GPIO bias, rolling RPM observation, exclusive input
claims, source timestamps and diagnostic status/metrics. Preserve existing
Fan/CoolingZone values and thermal control when feedback is omitted. Align the
operator chart version and appVersion with application 1.1.0, document explicit
CRD upgrades and rollback, and retain physical verification as follow-up #69.
