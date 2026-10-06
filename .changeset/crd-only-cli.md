---
"pifanctl": major
---

Removed(cli): require the Kubernetes operator for hardware control

Remove the standalone start command and legacy routing path. Local YAML worker execution now requires mock mode; real workers consume operator-managed plans with Node UID and heartbeat. Keep topology validation, Kubernetes inspection/apply, local sensor status, and temperature-agent commands. Update the English and Korean READMEs to use the single operator chart and preserve historical v0 instructions in a separate archive. Image smoke checks now verify a genuine hardware-driver refusal rather than a failed CLI invocation.
