# Meaningful software coverage audit

## Scope

The application coverage target includes every file under `sources/`, including
legacy code that is still shipped. Tests and release/report scripts are outside
that existing measurement scope. This audit does not expand or reduce it.

The initial Python 3.14 baseline was 529 passing tests, 1893/1952 executable lines
(96.9775%) and 614/672 branch destinations (91.3690%). The final reviewed C-traced
application report covers 1956/1956 lines and 670/670 branch destinations.
Coverage is a software-path observation, not proof of hardware correctness.

## Rules for test doubles

| Boundary | Approach | Evidence and limit |
| --- | --- | --- |
| Model, planner and control | Real functions and objects | Defaults, schema rejection, hashing, ownership, hysteresis and exact duty decisions |
| Thermal and configuration files | Temporary files with the actual format | Real parsing, reload, missing files and size limits; no physical temperature claim |
| CLI | Real Typer parsing, commands and script entry point | Input rejection and real mock-mode local execution; no host PWM changes |
| HTTP and metrics | Real localhost worker/Prometheus servers | Serialization, decoding, readiness and actual scrape text; no live cluster deployment |
| Kubernetes API | In-memory API boundary or official client with substituted transport | Optimistic conflicts, RBAC failure, deletion races and watch recovery; not API-server conformance |
| GPIO and PWM driver | Driver/input boundary substituted; actual constructors and reader logic retained | Kernel packet decoding, cleanup and failure handling; not measured voltage, RPM or duty |
| Scheduling and faults | Controlled threads/events or injected external IO failures | Deterministic timeout/shutdown tests; not comprehensive race exploration |

Boundary-value cases have explicit contracts: report freshness accepts ages from
-5 to 90 seconds, node identity must match, plans may not exceed the unchanged
900 KB limit, missing sensors demand failsafe, and acknowledged actuator release
must not recreate a worker after restart. Distinct cases exercise different
outcomes or guards. No resource-size constant is lowered to force an error.
Malformed public YAML, plans and remote reports are valid negative inputs for
trust-boundary tests; tests do not replace validators or control algorithms to
manufacture a desired result.

## Existing suite review

The audit searched tests for constructor bypass, private-state injection,
coverage exclusions and replacement of validators, planners, hashes or size
limits. Five GPIO reader tests used `__new__` followed by hand-built fields.
They now execute normal constructors while substituting GPIO acquisition and
thread scheduling. A newly drafted event-retry case duplicated an existing
behavioral scenario and was removed during the audit. Startup failure and stalled-thread cases continue to inject
those boundary failures explicitly.

Existing temperature-source, kernel ioctl, driver, telemetry and Kubernetes
fixtures remain appropriate at unavailable hardware/remote boundaries. The
multi-rack and per-board scenarios remain software safety tests with simulated
sensor inputs. Their results must not be presented as physical cooling or
large-cluster acceptance. Existing watchdog-latch tests represent deliberate
interleavings; they are not claimed as a concurrency proof.

The new integration paths also exercise real file loading, the local development
CLI, worker HTTP reports and a Prometheus scrape. Fault-injection unit tests are
retained where a healthy localhost server cannot reproduce RBAC, lease conflicts,
GPIO failures or concurrent Kubernetes garbage collection deterministically.

## Source review

The operator iterates `active | configs.keys()`, and `owners` contains every
active node. A node absent from `owners` therefore has an owned config. The old
third branch, which silently continued when neither existed, was unreachable
for ordinary dictionaries. It was removed rather than tested with fabricated
mapping behavior. This removes two branch destinations; it changes no reachable
runtime outcome. Inline safety checks were expanded for readable tracebacks.

No `no cover`, `no branch`, omit pattern or new coverage exclusion was added.
The 12 previously excluded lines belong to the `Controller` and `PwmDriver`
protocol declarations and remain unchanged.

## Measurement consistency and gates

Coverage.py 7.16.2 defaults to `sysmon` on Python 3.14. Cross-measuring the same
suite with `ctrace` showed different branch accounting, including generator
exhaustion and exception transitions. `.coveragerc` explicitly selects the
supported C tracing core for local tests, CI, Codecov uploads and badges.
A cross-core run of the same final source covered all 1956 executable lines
with both cores. C tracing recorded all 670 destinations; sysmon recorded
660/670. Its ten missing destinations were function-exit transitions from
comprehensions/generators, inline exception paths and the reconciliation loop.
Tests asserting the corresponding behavior passed under both cores. This is
measurement configuration, not a reduction in the measured source set.
See the [official core documentation](https://coverage.readthedocs.io/en/7.16.2/config.html#run-core).

Both report generation and downloaded-artifact validation enforce 100% line and
branch floors from raw counts. A rounded percentage cannot conceal a missing
branch, and a zero branch denominator cannot pass. Codecov project and patch
statuses require 100% with zero tolerance. Detailed PR comments remain visible,
missing reports fail, and carryforward stays disabled.

## Separate acceptance work

Full software coverage does not certify physical fan rotation, tachometer
pulses per revolution, probe wiring, voltages, PWM waveform fidelity, airflow,
thermal stabilization, Kubernetes API-server semantics, deployment recovery or
large-cluster scale. Those remain distinct acceptance procedures. New behavior
must add tests for meaningful contracts rather than arbitrary dummy variations.
