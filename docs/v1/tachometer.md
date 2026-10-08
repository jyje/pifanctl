# Optional tachometer feedback in v1.1

Application and operator chart 1.1.0 add optional RPM observation to an existing
Fan. Existing `values.yaml`, Fan and CoolingZone declarations remain valid.
Omitting `spec.feedback` allocates no tachometer input. PWM pins, frequency,
curves, temperature freshness, failsafe and exit duty keep their existing behavior.
The operator chart version and `appVersion` follow the application version;
an empty `image.tag` selects `v<appVersion>`. Explicit image overrides remain supported.

## Declare the input

Add this block to a Fan's existing `spec`, either in a separate manifest or in
`extraResources`. Keep the existing hardware, control and CoolingZone fields.
The [complete values example](../../tests/fixtures/operator-tachometer-values.yaml)
shows both resources. Names and pins in the example are illustrative.

```yaml
extraResources:
  - apiVersion: pifanctl.jyje.online/v1
    kind: Fan
    metadata:
      name: rack-fan-01
    spec:
      nodeName: pi-01
      hardware:
        rpigpio:
          pin: 18
          frequencyHz: 1000 # Preserved example, not Noctua frequency certification.
      feedback:
        tachometer:
          gpio:
            pin: 23       # BCM numbering: physical header pin 16.
            pull: up      # Internal 3.3 V bias; default off; also accepts down.
          pulsesPerRevolution: 2
          sampleSeconds: 5
```

| Field | Default | Contract |
| --- | --- | --- |
| `gpio.pin` | Required when enabled | BCM 0-27; different from the PWM pin |
| `gpio.pull` | `off` | `off`, `up`, or `down`; requested input bias |
| `pulsesPerRevolution` | `2` | Integer 1-16, match the fan specification |
| `sampleSeconds` | `5` | Integer 1-60, rolling RPM window |

The initial real backend supports Raspberry Pi 4 with `hardware.rpigpio` and
Linux GPIO character-device v2 (introduced in Linux 5.10). Pi 5/sysfs tachometer
inputs are not supported in this release. `--mock` never opens GPIO and reports
`MockInput`, without invented RPM.

### Electrical and channel requirements

For the NF-A12x25 PWM, fan pin 3 is the open-collector tachometer output with two
pulses per revolution. It reports speed, not actual PWM duty or frequency. Fan
pin 4 is the PWM input. See the [Noctua PWM specification](https://www.noctua.at/pub/media/wysiwyg/Noctua_PWM_specifications_white_paper.pdf).
Verify connector continuity and signal voltage before enabling a GPIO bias.
Cable extensions can use different colors. Never connect a 5 V or 12 V pull-up
to the Raspberry Pi input. The internal pull-up is a weak bias to 3.3 V, not a
signal amplifier or proof of voltage compatibility.

The worker claims the input exclusively through Linux GPIO v2, refuses an
existing output or alternate function, and detects input/output and input/input
conflicts between Fans on the same Node. A Fan conflict uses the existing
failsafe path. Kernel consumers can refuse a claim with `EBUSY`. Unrelated direct
GPIO writers bypassing kernel ownership still require correct operator wiring
and process isolation. Bias support is hardware dependent; a successful request
is not electrical verification. See [Linux GPIO v2 line requests](https://docs.kernel.org/userspace-api/gpio/gpio-v2-get-line-ioctl.html).

Removing feedback, changing its configuration or deleting the Fan closes its
reader and releases the line. Closing the GPIO request does not promise to
restore the previous bias; the kernel describes the released line as uncontrolled.
No global GPIO cleanup is performed on the PWM outputs by the tachometer reader.

## Observe status and metrics

```sh
kubectl get fan rack-fan-01 -o jsonpath='{.status.feedback.tachometer}'
kubectl pifanctl fan describe rack-fan-01
```

`status.feedback.tachometer` exposes `ready`, `reason`, `sampleSeconds` and
`pulseCount`. A complete valid window additionally exposes `rpm` and `observedAt`.
The worker counts falling edges using kernel monotonic timestamps:
`RPM = pulseCount * 60 / (pulsesPerRevolution * sampleSeconds)`.
Observation time is wall-clock time associated with collector progress. Operator
status updates use the existing 30-second rate limit; scrape worker metrics for
more frequent observations.

| Reason | Interpretation |
| --- | --- |
| Empty reason, `ready: true` | Full window with valid pulse observations |
| `WarmingUp` | Full observation window not yet collected; RPM omitted |
| `NoPulses` | Complete window with zero observed edges; RPM zero, feedback not ready |
| `CollectorStale` | Reader progress older than two seconds; RPM omitted |
| `EventSequenceGap` | Lost kernel events; restart/reconfigure reader before trusting RPM |
| `InvalidEventClock` | Invalid or reversed event timestamps; RPM omitted |
| `SignalOverflow` | More than 10,000 retained edges; RPM omitted |
| `CollectorError` | Read or snapshot failed; RPM omitted |
| `Unavailable` | Input initialization failed; RPM omitted |
| `MockInput` | Hardware-free execution; RPM omitted |

Zero pulses can mean a stopped fan, missing wiring, unsuitable bias or another
signal problem. It does not by itself prove the fan stopped. This release is
observational: tachometer failure does not change thermal Ready, duty, failsafe
or PWM frequency. A collector initialization failure is retried on feedback
configuration change or worker restart. Fault latching and RPM-based control are
outside this release.

Worker metrics, labeled by `node` and `fan`:

- `pifanctl_worker_fan_rpm`: observed RPM, absent when unknown.
- `pifanctl_worker_fan_tachometer_ready`: 1 for a complete valid pulse window, otherwise 0.
- `pifanctl_worker_fan_rpm_observed_timestamp_seconds`: source observation time, absent when unknown.

Unknown RPM is removed from metrics and CR status instead of retaining a stale
number or presenting zero. Omitting feedback also removes its status and series.

## Upgrade and rollback

1. Review the new CRD schemas and make the 1.1.0 image available.
2. Apply the updated CRDs explicitly. Helm installs CRDs on first installation
   but does not upgrade them on `helm upgrade`:

   ```sh
   kubectl --context lab apply --server-side -f charts/pifanctl-operator/crds/
   ```

   Resolve field ownership conflicts through the existing GitOps owner; do not
   force conflicts. See the [runtime manual](runtime.md) for Argo CD ordering.
3. Upgrade the operator chart and runtime to 1.1.0 using existing values first.
   If using the legacy-CA image, select `v1.1.0-py312` after it is published.
4. Verify operator/worker readiness and the unchanged thermal plan. Verify the
   electrical input separately, then add the optional feedback declaration.
5. Check collector readiness, RPM response and freshness. Actual fan rotation,
   signal voltage and PWM waveform require physical observations or instruments.

To roll back, remove `feedback` first and wait for the worker to acknowledge the
new plan and release its GPIO claim. Then restore the older runtime and chart.
The additive CRD can remain installed. Downgrading the schema can prune new
fields and must be reviewed separately. An older runtime is not compatible with
an enabled feedback plan; do not roll back the image while retaining that plan.

## Verification boundary

The v1.1 PR verifies schema defaults, plan claims, status clearing, event ABI,
collector failures, mock behavior, worker lifecycle and existing/new Helm values
using automated tests. It does not certify physical GPIO voltage, RPM accuracy,
Pi 5 input support or Noctua PWM waveform compliance. Physical experiments remain
tracked in [issue #69](https://github.com/jyje/pifanctl/issues/69) and broader
release follow-up [#64](https://github.com/jyje/pifanctl/issues/64).
