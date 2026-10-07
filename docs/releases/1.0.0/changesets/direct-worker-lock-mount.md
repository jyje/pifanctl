---
"pifanctl": patch
"pifanctl-operator": patch
---

Fix(worker): use a direct container lock mount and verify active runtime lifecycle

Mount the existing host lock at `/run/lock/pifanctl` inside operator-managed
workers, preserving the host path shared with earlier controllers. Add an
explicit simulated-I/O Kubernetes lab for worker placement, multi-fan control,
sensor loss/recovery and cooperative finalization. Document the kind node's
required lock-directory preparation separately from the container mount change.
