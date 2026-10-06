---
"pifanctl": minor
"pifanctl-operator": minor
---

Feature(api): serve stable v1 topology resources with alpha compatibility

Serve identical Fan and CoolingZone schemas at v1 and v1alpha1, store new writes at v1, and preserve the alpha endpoint for existing clients. Normalize alpha YAML to v1 without changing topology identity or plans. Document ordered CRD upgrades, complete storage rewrites and reverse rollback. Bump the operator chart independently and pin the alpha.5 runtime. Stable hardware acceptance remains pending.
