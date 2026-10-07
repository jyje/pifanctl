# Changelog

Application and operator chart versions are independent. Both start the stable v1 series at 1.0.0. This entry is a release proposal until the corresponding artifacts and GitHub releases are published.

## Application 1.0.0

### Features

- Manage shared-rack cooling and one fan per board through stable `pifanctl.jyje.online/v1` Fan and CoolingZone resources. Keep identical served v1alpha1 schemas for migration compatibility.
- Resolve cooling members by Node names or labels. Each actuator follows the hottest assigned member plus its local sensor.
- Reconcile one node-bound hardware worker per actuator Node, with channel claims, Node UID checks, a shared host lock and operator heartbeat.
- Manage topology through the Kubernetes-aware CLI and kubectl plugin, including validation, planning, inspection and server-side apply.
- Report temperature acquisition clocks and worker status. Request failsafe duty on missing/stale inputs or expired heartbeat.
- Apply curve hysteresis and rate-limited falling duty to reduce oscillation.

### Breaking changes

- Remove standalone `start` control. Kubernetes CRDs and operator-managed hardware workers are required. Local YAML workers require `--mock`.
- Remove ConfigMap-based topology selection. Declare instances as CRs directly or through the operator chart extraResources array.
- Retire the legacy pifanctl chart from the v1 publishing contract. Historical v0 instructions remain archived.

### Fixes and verification

- Use a direct container mount for the shared host PWM lock. Preserve cooperative finalization and ownership checks.
- Verify stable/alpha storage migration, reverse storage rollback, runtime image rollback, minimum Kubernetes 1.30 compatibility and Argo CD lifecycle.
- Retain branch coverage and revision-stamped line/branch badge reporting across Python 3.10-3.14.

## Operator chart 1.0.0

- Publish the single supported operator chart as `oci://ghcr.io/jyje/charts/pifanctl-operator`.
- Default to application 1.0.0. Later application releases do not implicitly update the chart image pointer or chart version.
- Install Fan/CoolingZone definitions and render declared instances from extraResources.
- Retain shared CRDs across Argo CD pruning/deletion; retire active CRs cooperatively before removing their operator.
- Include operator, temperature-agent, RBAC, worker metrics and network-policy configuration. Prometheus remains an external dependency.

## Verification scope and deferred work

The practical campaign used a mixed Raspberry Pi 4/Pi 5 rack with one shared fan and four members. Pi 4 Model B Rev 1.5 controlled GPIO18; Pi 5 Model B Rev 1.0 was the observed CPU-load/temperature member. Pi 5 actuator behavior is not physically verified.

The unchanged 50 C observation passes the approved 3 C policy. New bounded 55 C and 60 C loads raised temperature but did not sustain the prescribed 120-second plateau. Cleanup and cooldown passed; failed verdicts remain unchanged. The controller implements a temperature-to-duty curve, not exact temperature-setpoint regulation.

Electrical PWM/RPM, exact fan/supply/wiring, physical reboot/power-loss/network faults, Pi 5 actuation, expanded full v0 topology rollback and distributed fleet saturation remain follow-up work in [issue #64](https://github.com/jyje/pifanctl/issues/64). Simulated 16-fan/64-zone lab checks do not certify physical capacity or electrical safety. The maintainer accepted these limitations for practical verification closeout and release preparation.

The live acceptance runtime used an alpha.6 Python 3.12 compatibility image with TLS verification enabled. The release pipeline publishes canonical Python 3.14 `v1.0.0` and a Python 3.12 compatibility variant `v1.0.0-py312`. Only the canonical runtime updates `latest`; both immutable variants must build successfully before the application release is created. Software CI covers both runtimes, but production adoption of the stable image requires its own TLS/telemetry and runtime checks, particularly with a legacy certificate authority. The candidate Python 3.14 handshake failed because the current cluster CA lacks a key-usage extension. Select the explicit Python 3.12 version tag for this legacy-CA deployment, retain certificate/hostname verification, and complete candidate runtime and rollback checks before adoption. CA modernization remains separate cluster maintenance.

See the [acceptance report](docs/v1/release-acceptance.md) and [archived changesets](docs/releases/1.0.0/changesets). Entries naming the legacy chart are historical provenance and do not publish a new legacy chart version.
