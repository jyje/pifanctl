# Hardware verification campaign: NF-A12x25 PWM

Status: **in progress, physical acceptance not achieved**. App/chart 1.1.0 is
installed. The existing Pi 4 actuator serves a four-member mixed Pi 4/Pi 5 rack.
Pi 5 fan actuation and a larger physical fleet are separate unverified scope.

## 01: Signal identification

| Signal | Fan direction | Meaning | Evidence required |
| --- | --- | --- | --- |
| PWM, fan pin 4 | Into fan | Requested speed control waveform | Connector-level frequency, duty, voltage, polarity |
| Tach, fan pin 3 | Out of fan | Two pulses per revolution | Pi-safe input, pulse acquisition, independent rotation check |
| Commanded duty | Software value | Controller request | CR status and worker report, not actual rotation |

The [Noctua specification](https://www.noctua.at/pub/media/wysiwyg/Noctua_PWM_specifications_white_paper.pdf)
requires a PWM target of 25 kHz, acceptable 21-28 kHz. Its tachometer is open
collector and requires a suitable pull-up to obtain a HIGH state. The PWM pin has
an internal pull-up; these are different electrical interfaces. Check the actual
voltage/interface and extension continuity. Confirm the fan nameplate and supply
voltage separately: the standard NF-A12x25 PWM is a 12 V model, while the 5 V
variant has a distinct model designation. A 12 V fan powered from a Pi 5 V pin
must not be compared with the rated 12 V speed curve. Current supply voltage is
not remotely verified. Do not connect a 5 V or 12 V-biased
signal directly to a Pi input. Noctua recommends a CMOS drive circuit and warns
that open-collector PWM drive can deform the waveform. A generic transistor
circuit must not be assumed compliant without validation.

## 02: Completed passive observation

[Summary JSON](passive-summary.json), [raw anonymous transitions](passive-transitions.csv),
[chart](passive-observation.png), and [PDF report](../../../output/pdf/pifanctl-hardware-verification.pdf).

| Quantity | Observed |
| --- | --- |
| Duration | 10.00001 seconds |
| GPIO samples | 3,161,163 |
| Complete rising-edge cycles | 8,432 |
| Configured software PWM | 1,000 Hz |
| Median observed cycle frequency | 892.54 Hz |
| Commanded duty around the capture | 35.04% |
| Median observed HIGH ratio | 36.59% |
| Median / p99 polling gap | 2.95 / 7.56 microseconds |
| Maximum polling gap | 38.28 milliseconds |
| Tach falling edges | 0, with the existing pull-down |
| Pin function/pull registers | Unchanged before/after capture |
| Worker outcome | Ready/Regulating, no restart |

This is userspace observation of SoC GPIO register levels with read-only memory
mapping. It does not measure fan connector voltage, cable continuity, electrical
polarity, analog rise/fall times or calibrated jitter. Missed events are possible
in long scheduler gaps. The CPU observer can itself disturb software PWM.
Observed HIGH ratio is not tach RPM or airflow. The absence of tach pulses with
pull-down is inconclusive about rotor motion. No fan stop or duty sweep occurred.

**Finding:** neither the configured 1 kHz output nor this uncalibrated capture
establishes the required Noctua 21-28 kHz signal. Resolve the frequency/interface
path before declaring specification compliance or running the formal sweep.

Reproduction on the existing Pi 4 actuator, after reviewing the script and
confirming the expected pin mapping:

```sh
kubectl --context lab -n pifanctl exec -i WORKER_POD -- python - \
  < scripts/observe_gpio_levels.py > private-observation.json
python scripts/analyze_gpio_observation.py private-observation.json
python scripts/build_hardware_observation.py
```

The report builder requires matplotlib and reportlab. It supports `--chart-only`
and `--pdf-only` when the libraries are provided by separate environments.

The committed collector improves the exploratory capture with a bounded
100,000-sample quantile tail, a 30,000-transition limit and a node-local 60 C
cutoff. Its outputs therefore need not reproduce the first capture byte for
byte. It never requests a GPIO line, changes bias or writes PWM. Its fixed
GPIO18/GPIO23 mapping must be reviewed for another installation.

## 03: Inspection and hardware PWM readiness

- [x] Confirm published 1.1.0 runtime and four-member managed telemetry.
- [x] Preserve the deployed baseline and verify retained rollback artifacts.
- [x] Collect passive existing-output transitions without pin changes.
- [x] Confirm no `/sys/class/pwm/pwmchip*` is exposed in the current worker.
- [ ] Confirm the exact installed fan, supply, ground and adapter continuity.
- [ ] Confirm tach voltage is Pi-safe and that no external 5 V/12 V bias exists.
- [ ] Confirm fan-connector PWM voltage/frequency/polarity with instruments.
- [ ] Review a kernel hardware-PWM overlay and channel mapping on the Pi 4 host.
- [ ] Arrange a controlled actuator handoff and verified independent cooling
      before enabling an overlay or rebooting. No concurrent GPIO/PWM writers.
- [ ] Validate hardware PWM at 25 kHz under load using connector-level capture.

The existing sysfs backend can use a kernel PWM channel after the correct host
overlay is installed. The current host exposes no PWM chip to the worker. Do not
merely set RPi.GPIO software PWM to 25,000 Hz and call it hardware PWM. Map the
actual exposed chip/channel and overlay pin on the host rather than guessing.
A Fan's hardware is immutable, so the switch requires acknowledged replacement
and preservation of CoolingZone ownership. This is a planned handoff, not an
already executed configuration change. See [Linux PWM](https://docs.kernel.org/driver-api/pwm.html)
and [Raspberry Pi overlays](https://www.raspberrypi.com/documentation/configuration/device-tree.html).

## 04: Tach acquisition baseline

After electrical inspection passes, declare `feedback.tachometer` with the
verified BCM input and appropriate 3.3 V bias. Use two pulses/revolution for the
NF-A12x25 PWM. See [the runtime guide](../tachometer.md).

- [ ] Keep the existing cooling policy and one hardware worker.
- [ ] Wait for a full valid sample window and collect 60 seconds of RPM, pulse
      counts, source timestamps, commanded duty and every member's temperature.
- [ ] Compare observed speed with physical rotation and the product rating.
- [ ] Investigate missing pulses as wiring/bias/collector uncertainty before
      labeling the fan stopped. Never use commanded duty as measured RPM.

## 05: Bounded duty/RPM campaign

Only execute after connector-level PWM and usable tach acquisition pass.

1. Archive current GitOps values, CRDs, Fan/CoolingZone identities, plan hash,
   image digests and exact restoration instructions. Pause the relevant GitOps
   self-heal only through a tracked temporary declaration, restoring it afterward.
2. Use the existing managed worker as the only PWM writer. Prepare reviewed
   temporary curve values for 100%, 75%, 50% and 30% stages, with failsafe/exit
   100%. Preserve a rise to full duty as the hottest member approaches 60 C;
   abort a stage if the measured command no longer equals its target.
3. Install and verify an independent node-local temperature/deadline guard. It
   must fail to full cooling through the existing owner and remain effective if
   the remote runner or Kubernetes API connection disappears. Validate its
   restoration behavior before starting the first reduced-duty stage.
4. For each stage, confirm plan acknowledgement, settle at least 30 seconds
   (longer if the falling-duty limiter requires it), then record 60 seconds of
   fresh RPM and member temperature. Preserve every actual command transition.
5. Abort on any member reaching 60 C, missing/stale telemetry, unhealthy worker,
   collector error, loss of physical observation or deadline expiry. Mark aborted
   stages as aborted, not failed-speed measurements. Restore normal policy on
   every exit and verify fresh telemetry plus normal reconciliation afterward.
6. Publish anonymous CSV, RPM/time and duty/RPM plots with measured intervals,
   pulse resolution, uncertainty and missing data. Retain original raw records.

No uncontrolled fan stop, rotor obstruction, power removal, reboot or fleet
saturation is part of this first sweep. Those scenarios require their own
physical setup and recovery safeguards below.

## 06: Remaining hardware and scale matrix

| Gate | Current verdict | Required setup/evidence |
| --- | --- | --- |
| Tach baseline and duty/RPM curve | Not measured | Verified input and conforming PWM; stages above |
| PWM voltage/frequency/polarity | Not measured at connector | Scope or calibrated analyzer; voltage measurement |
| Startup/shutdown defaults | Not observed | Continuous physical rotation/RPM capture during controlled lifecycle |
| Reboot/power-loss/network partition | Not run physically | Independent cooling/power control, observer and rollback |
| Pi 5 fan actuation | Not run | Actual wired Pi 5 actuator and kernel PWM channel |
| Extended thermal holds | Deferred | Workload capable of reaching the intended temperature band |
| Full v0 topology rollback | Deferred | Retained v0 state/artifacts and scheduled owner handoff |
| Larger distributed fleet | Not run | Additional real actuators/members, measured telemetry capacity |

[Issue #69](https://github.com/jyje/pifanctl/issues/69) tracks the installed-fan
campaign. [Issue #64](https://github.com/jyje/pifanctl/issues/64) retains the broader
physical, thermal, rollback and scale scope. Existing simulated tests and green
CI do not satisfy these physical gates.
