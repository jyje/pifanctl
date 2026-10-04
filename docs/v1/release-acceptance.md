# pifanctl v1 Release Acceptance Field Manual

**Status:** Field procedures and evidence record, 2026-10-04
**Release target:** `1.0.0`
**Current implementation:** `1.0.0-alpha.1`
**Decision:** Not ready for a stable release. Hardware-specific acceptance remains open.

This manual turns the remaining release gates in [PLAN.md](../../PLAN.md) into repeatable checks. It distinguishes software-reported commands from measured electrical signals and physical cooling. A green condition, requested PWM duty, or spinning fan at one point in time is not proof of fail-open behavior.

## 1. Evidence rules

- Record the tested source commit, image digest, chart version, topology hash, node identity, and test timestamp for every run.
- Use an isolated test rack or a maintenance window for tests that stop workers, partition networking, reboot nodes, or remove power.
- Keep a person at the hardware for all fan and power tests. Record fan rotation directly. Use a tachometer when available, and an oscilloscope or logic analyzer for PWM signal measurements.
- Mark a check **Pass** only when its acceptance criteria and evidence are recorded. Use **Fail**, **Blocked**, or **Not run** for all other outcomes.
- Do not infer fan RPM from pifanctl duty. Duty is a requested signal value, not a rotation measurement.
- Stop on unexpected heating, loss of cooling, unstable power, or a signal state that cannot be explained. Restore the archived configuration using the documented rollback procedure.

## 2. Current trial baseline

Read-only snapshot from the configured MicroK8s cluster after the candidate rollout on 2026-10-04:

| Item | Observed value |
| --- | --- |
| Kubernetes context | `microk8s` |
| Nodes | `raspi-40`, `raspi-41`, `raspi-50`, `raspi-51` |
| Node runtime | Kubernetes `v1.36.2`, `arm64` |
| Trial namespace | `pifanctl-v1-trial` |
| Operator and worker image | `ghcr.io/jyje/pifanctl-issue:887f6f1-py312` |
| Runtime chart source | `pifanctl` commit `887f6f1ff05301255e7a5f01e22e117ef8e8e9ef` |
| Image build | [GitHub Actions run #25](https://github.com/jyje/pifanctl/actions/runs/37201259327), Python 3.12, successful image checks |
| Preserved pre-upgrade trial target | Chart source `837b3d5`; issue image `6a0f5a5-py312`, retained in the Application's previous applied configuration |
| Cooling zone | `r4spi-rack`, four named Nodes |
| Fan | `r4spi-rack-fan`, `raspi-40`, RPi.GPIO BCM pin 18, 1000 Hz |
| Reported state | Argo CD `Synced/Healthy`; operator, four agents, and worker Ready; Fan and CoolingZone Ready |
| Reported temperature | 49.05 C, from Prometheus at `2026-10-04T12:18:16Z` |
| Requested fan duty | 24.375% at the same observation |
| Physical observation | Post-upgrade visual confirmation is pending; the user confirmed normal rotation before this image update. No RPM or PWM waveform is recorded. |
| Topology source | Unchanged from commit `837b3d5`; shared rack configuration preserved |

This is a useful live baseline, not a release acceptance result. The current main-source candidate is deployed to the isolated trial, but no physical PWM waveform, RPM, reboot, power-loss, or network-partition test has been recorded. The Pi model and fan electrical details must be read from the physical inventory; node names alone do not prove board model. The earlier `6a0f5a5-py312` trial image remains the immediate rollback target, and the separately archived v0 configuration remains available for full rollback.

## 3. Hardware inventory and electrical safety

Complete one inventory row for each actuator and fan before applying a configuration:

| Field | Record |
| --- | --- |
| Raspberry Pi model and revision | ______________________________ |
| OS, kernel, firmware | ______________________________ |
| Node name and UID | ______________________________ |
| Driver and exact GPIO/PWM chip/channel | ______________________________ |
| Fan manufacturer, model, rated voltage/current | ______________________________ |
| Fan power source and fuse/current limit | ______________________________ |
| PWM input type, polarity, frequency range | ______________________________ |
| Ground/reference and signal wiring | ______________________________ |
| Independent pull/default circuit and measured default | ______________________________ |
| Tachometer or other rotation measurement | ______________________________ |

`100%` in pifanctl means a full-duty request. It does not prove the signal polarity is correct, that the fan has power, or that the motor is turning. A controller-board reboot, process crash, disconnected signal, or lost board power can leave the PWM input floating or inactive depending on the board, fan, driver, and circuit. The hardware design must give the fan's PWM input a measured safe default independent of pifanctl. The fan supply must remain available independently of the control process and must be correctly rated and protected. No universal pull-up, pull-down, or polarity is assumed by this project.

Do not promise cooling during complete fan-supply loss. If the workload requires cooling after a controller or signal failure, use a fan and external circuit whose documented default state has been verified for the actual wiring. Record both signal waveform and physical rotation. Software cannot compensate for an unpowered or mechanically failed fan.

## 4. Acceptance procedures

### A. Raspberry Pi 4 GPIO PWM

1. Record Pi model/revision, OS/kernel, fan model, power, exact wiring, pin, polarity, and instrument setup.
2. With the fan safely powered and a person observing it, start the worker on the actuator node. Capture the signal from process start through driver initialization.
3. Verify the initial full-duty request reaches the measured signal before telemetry is accepted. Measure frequency, duty, polarity, voltage levels, startup latency, and fan rotation.
4. Apply a known configuration and verify measured duty tracks the requested duty. Confirm the fan starts reliably from rest at the configured start duty and does not stall at each tested step.
5. Stop the worker normally. Verify the configured exit duty is emitted and the fan remains in the intended safe state.
6. Repeat at least three cold starts and three normal stops. Attach scope/tachometer records and logs.

**Pass:** measured waveform and fan behavior match the documented fan specification and configured duty at every tested point; startup and shutdown default behavior is repeatable. A 100% software request alone is not a pass.

### B. Raspberry Pi 5 kernel sysfs PWM

1. Confirm the supported kernel overlay, PWM chip, channel, pin mux, polarity, and frequency from the actual Pi 5. The sample `chip: 0`, `channel: 2` in `design/v1/examples/sysfs.yaml` is illustrative and must not be assumed correct for a board.
2. Record which kernel component owns the PWM channel and confirm there is no competing writer.
3. Repeat the waveform, start duty, stable duty points, normal shutdown, cold-start, and physical rotation measurements from procedure A.
4. Reboot the Pi and verify the signal's state from power-on through worker initialization. Capture any interval before the kernel driver and pifanctl take control.

**Pass:** actual chip/channel mapping is verified, there is one writer, waveform and physical behavior are repeatable, and the measured boot/shutdown defaults satisfy the hardware safety design.

### C. Process exit, crash, and watchdog

Test graceful stop and forced termination separately. A normal shutdown can run cleanup; `SIGKILL` cannot. Record signal and fan behavior for both. For the operator heartbeat test, interrupt only the isolated trial worker's access to fresh plan/heartbeat data and confirm the 120-second watchdog behavior without affecting unrelated workloads.

**Pass:** graceful stop applies the documented exit state; forced termination and stale heartbeat reach the independently designed safe electrical default; the operator reports stale or unready state; recovery requires fresh matching plan/heartbeat acknowledgement. Any measured behavior that depends on Python cleanup is not accepted as protection against `SIGKILL`.

### D. Node reboot and power loss

On an isolated actuator host, separately test orderly reboot, abrupt controller power loss, and fan-supply interruption. Do not combine failure causes in a single run. Observe the physical fan and capture signal voltage during each transition. Confirm the independent fan supply behaves as designed. Restore one failure at a time and verify the worker reclaims the hardware lock without competing writers.

**Pass:** each failure has a measured, documented outcome. If cooling cannot continue during a particular failure, state that limitation explicitly and keep the stable-release gate open unless the product's safety requirements accept it.

### E. Network partition and telemetry loss

In the isolated trial only, interrupt worker-to-operator heartbeat delivery and separately interrupt Prometheus telemetry. Record when the fault begins, when the worker enters failsafe, requested and measured PWM, `/readyz`, metrics, and recovery. Keep the assigned fan and expected member set unchanged during the test.

**Pass:** stale/missing telemetry and expired worker heartbeat do not lower duty; the worker stays unready/degraded with a visible reason; recovery uses fresh data and matching configuration identity.

### F. Migration and rollback

1. Capture the archived v0 configuration and its checksum. Inventory all processes that can write each PWM channel.
2. Compare a read-only v1 topology plan with the physical rack. Keep the fan at full speed during handover.
3. Stop the legacy writer and verify it has released the hardware before starting the v1 worker. Confirm the host-wide lock prevents a second writer.
4. Exercise rollback: stop v1, verify driver close and lock release, restore the archived v0 configuration, then verify the original controller and cooling behavior.
5. Repeat for every documented driver/topology combination, including a single Pi fan and shared rack fans.

**Pass:** no overlapping writers occur, handover and rollback are repeatable, all nodes/fans return to the intended configuration, and the archive is usable.

### G. Fleet load

Define a supported fleet size before testing: number of Nodes, CoolingZones, Fans, worker endpoints, and scrape interval. At that size, measure operator CPU/memory, API requests, reconciliation duration, status writes, Prometheus query latency, scrape gaps, and worker heartbeat age during steady state and recovery. Use representative synthetic telemetry first; do not generate load against the production API without a maintenance plan.

**Pass:** all workers remain within freshness limits, no stale state is reported Ready, API and Prometheus load stay within the cluster's documented budget, and status writes do not create unbounded etcd churn.

## 5. Evidence record

Use a separate record for every run. Attach raw logs, scope captures, and tachometer data to the project evidence archive and reference their checksum here.

| Run | Candidate commit/image digest | Procedure | Result | Evidence reference/checksum | Reviewer/date |
| --- | --- | --- | --- | --- | --- |
| 1 | __________________ | __________________ | Not run | __________________ | __________________ |
| 2 | __________________ | __________________ | Not run | __________________ | __________________ |
| 3 | __________________ | __________________ | Not run | __________________ | __________________ |

### Release gate summary

| Gate | Current state | Required evidence |
| --- | --- | --- |
| Pi 4 GPIO waveform and physical fan behavior | Open | Procedures A and C results on the release candidate |
| Pi 5 sysfs mapping and behavior | Open | Procedure B results on the actual supported Pi 5 setup |
| Process/node/power/network failures | Open | Procedures C, D, and E with measured signal/rotation and recovery |
| Migration and rollback | Open | Procedure F for each supported configuration |
| Supported-fleet load | Open | Procedure G measurements at a declared fleet size |
| Safety limitations documented | Documented, hardware validation open | Inventory, measured defaults, independent supply, and explicit failure limits |

## 6. Release decision

Do not label `1.0.0` stable until every applicable gate is backed by evidence for the exact release candidate. Hardware or topology combinations that were not tested must be clearly listed as unsupported. Preserve the alpha rollback archive until the release decision is recorded.

## References

- [Runtime manual](runtime.md)
- [v1 architecture and acceptance design](README.md)
- [Implementation and release checklist](../../PLAN.md)
- [RPi.GPIO project](https://sourceforge.net/projects/raspberry-gpio-python/)
- [Linux kernel PWM interface](https://docs.kernel.org/driver-api/pwm.html)
