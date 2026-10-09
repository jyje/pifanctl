# Optional PWM probe feedback (v1.2)

The app and operator chart introduce this additive feature at **1.2.0**. It is a
compatible feature addition, so 1.1.1 would understate the release. CR API/storage
remain `pifanctl.jyje.online/v1`, with the identical served v1alpha1 schema.

## Configure only a verified independent input

```yaml
spec:
  # Existing nodeName, hardware and control remain unchanged.
  feedback:
    pwm:
      gpio:
        pin: 24        # Example BCM number, not a wiring instruction
        pull: off      # Default: do not bias the observed signal
      sampleSeconds: 1 # Default 1, allowed 1-5 seconds
    tachometer:
      gpio:
        pin: 23
        pull: up
      pulsesPerRevolution: 2 # User must confirm for the specific fan
      sampleSeconds: 5
```

`pwm` and `tachometer` are independently optional. Existing tach-only or feedback-free
Fan declarations and Helm `extraResources` values remain valid. Empty feedback
objects are rejected. The current backend supports Pi 4/rpigpio with Linux GPIO
v2. Input pins must differ from each other and every claimed PWM output on the
same node. Busy/output/alternate-function pins are refused. Probe collection
never changes the output frequency, duty or thermal failsafe.

Before connecting, the user must verify signal continuity, common ground and a
Pi-safe signal no higher than 3.3 V at the **probe input**. Use a suitable level
interface for an incompatible signal. The example pin is not remotely verified.
Do not connect a fan supply rail or use the existing PWM output pin as the input.
Leave the probe omitted until the physical wiring is confirmed. An internal
pull-up is not a voltage converter. Biasing a probe can affect its observed line.

Apply the new chart CRDs explicitly before enabling the fields; Helm does not
upgrade installed CRDs automatically. See [CRD upgrade/rollback](tachometer.md).
Remove `feedback.pwm` and wait for worker acknowledgement before rolling back to
1.1.0. An old binary must not receive a worker plan containing the new field.
No production probe is enabled by this PR.

## What is measured

The collector requests both rising and falling edge events with kernel monotonic
timestamps, using exclusive input ownership. Complete rise/fall/rise cycles give:

- frequency = complete cycles / summed cycle durations;
- HIGH duty = summed HIGH durations / summed cycle durations * 100.

The rolling window must be complete and contain at least two cycles. Missing
sequence numbers, invalid timing/order, bounded-buffer overflow, collector
failure and stale progress invalidate the measurements. A static HIGH/LOW input
has insufficient cycles: it displays N/A instead of guessing 0% or 100% duty.
Kernel event sequence checks detect queued event loss; they cannot prove the
hardware captured every edge. High-frequency acquisition may overload the kernel
or reader and must be validated on the actual installation. Digital input timing
does not certify analog voltage, rise/fall shape, polarity at the fan connector,
calibrated jitter or manufacturer waveform compliance. An inverting interface
makes HIGH duty the complement of the original signal: verify the interface.

See the [Linux GPIO v2 event contract](https://docs.kernel.org/userspace-api/gpio/gpio-v2-line-event-read.html).

## Availability contract

| Probe state | CR state / CLI display | Numeric Prometheus samples |
| --- | --- | --- |
| Omitted | NotConfigured / N/A | NaN |
| Complete valid window | Measured frequency and HIGH duty | Frequency, duty, acquisition clock |
| Warming, static, stale, failed or lost events | Reason / N/A | NaN |

`status.feedback.pwm` carries `ready`, `reason`, `sampleSeconds` and
`cycleCount`. Valid samples additionally carry `frequencyHz`, `dutyPercent` and
`observedAt`. Old numeric fields are cleared with null merge patches when the
measurement becomes unavailable. Thermal Ready remains independent of feedback.
Prometheus has no string N/A sample: unavailable PWM measurement samples use NaN.
Configure dashboards to display missing values as N/A, never fill them with zero
or the commanded duty. Every tracked Fan exposes separate configured and ready gauges (0/1).
Unavailable measurements use NaN, never zero or the commanded duty.

```sh
pifanctl --context microk8s fan measurements FAN_NAME
kubectl get fan FAN_NAME -o jsonpath='{.status.feedback.pwm}{"\n"}'
```

```promql
pifanctl_worker_fan_pwm_frequency_hz
pifanctl_worker_fan_pwm_duty_percent
pifanctl_worker_fan_pwm_probe_configured
pifanctl_worker_fan_pwm_probe_ready
time() - pifanctl_worker_fan_pwm_observed_timestamp_seconds
```

The existing worker ServiceMonitor collects these metrics without new scraping
infrastructure. CLI observation summaries reject acquisition clocks older than
60 seconds; Prometheus users should also filter by ready and source-clock age.

## RPM requires per-fan confirmation

`pulsesPerRevolution: 2` remains the compatibility default, not a universal fan
contract. **The user must verify this value for each fan model and adapter path**
from its specification or independent measurement. Wrong pulse counts scale the
reported RPM incorrectly. RPM also depends on supply voltage, model, load and
installation; a duty percentage does not imply the same RPM across fans. Tach
pulses alone do not measure airflow or provide independent calibrated accuracy.
Zero pulses may mean a stopped rotor, disconnected wire or unsuitable bias.


### Prometheus representation decision

N/A is a presentation label, not a Prometheus numeric value. The [official
exposition format](https://prometheus.io/docs/instrumenting/exposition_formats/)
accepts numeric floating-point samples including NaN; this exporter deliberately
exports NaN for unavailable PWM measurements, following the maintainer preference,
and exports explicit 0/1 configured/ready gauges.
This distinguishes an unconfigured probe from a configured but failed probe.
CR fields retain typed booleans/reasons and omit unavailable numbers; the CLI
renders those states as N/A. This is a project availability contract, not a claim
that Prometheus mandates one universal missing-data representation.

Use `absent()` for unexpected missing state series and `up` for scrape failure,
not for concluding that a missing measurement means a stopped fan. Historical
range queries still contain previously measured samples. Unavailable PWM samples remain present as NaN after the next worker cycle/scrape.
A removed Fan loses its series after a successful scrape observes removal.
Dashboard NaN/null handling must not replace unknown samples with zero.


NaN can propagate through arithmetic and aggregation. Filter by readiness before
computing a mean, comparison or alert:

```promql
pifanctl_worker_fan_pwm_duty_percent
  and on(node, fan) (pifanctl_worker_fan_pwm_probe_ready == 1)
```

Also require a recent source timestamp and successful scrape for alert decisions.
Do not put NaN in CR JSON/YAML numeric fields: those remain absent with an explicit
reason. NaN is an ordinary unavailable sample here, not a manually emitted
Prometheus stale-marker value. RPM's existing zero-pulse and invalid-sample
contract is unchanged.
