---
"pifanctl-operator": minor
"pifanctl": patch
---

Feature(operator-chart): support CRD-first Fan and CoolingZone instances

The v1 operator chart now provides the single CRD-based installation path and accepts cooling instances through its extraResources values. The operator command no longer exposes ConfigMap topology selection.
