---
"pifanctl": minor
"pifanctl-operator": minor
---
Feature(feedback): optional independent PWM probe measurements

Add opt-in Pi 4 digital PWM frequency and HIGH-duty observations through a
separate GPIO input. Publish valid measurements and acquisition timestamps in
CR status and Prometheus; export NaN for unavailable Prometheus measurements and typed CR reasons/CLI
N/A when absent, stale or invalid. Preserve existing values and thermal failsafe, require user
verification of each fan's tach pulses per revolution, and align app/chart
versions at 1.2.0. Physical probe wiring and calibration remain explicit gates.
