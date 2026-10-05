# Trouble Shooting

## Build: externally-managed-environment

In Raspberry Pi, if you encounter the following error:

```sh
error: externally-managed-environment

× This environment is externally managed
╰─> To install Python packages system-wide, try apt install
    python3-xyz, where xyz is the package you are trying to
    install.
    
    If you wish to install a non-Debian-packaged Python package,
    create a virtual environment using python3 -m venv path/to/venv.
    Then use path/to/venv/bin/python and path/to/venv/bin/pip. Make
    sure you have python3-full installed.
    
    For more information visit http://rptl.io/venv

note: If you believe this is a mistake, please contact your Python installation or OS distribution provider. You can override this, at the risk of breaking your Python installation or OS, by passing --break-system-packages.
hint: See PEP 668 for the detailed specification.
```

Then you can try the following command:

```sh
python3 -m venv ~/.pifanctl/sources/venv
source ~/.pifanctl/sources/venv/bin/activate

pip install --upgrade -r requirements.raspi.txt

# To deactivate the virtual environment, you can run the following command:
# deactivate
```

## Build: RPi.GPIO on a machine that is not a Raspberry Pi

`RPi.GPIO` only builds and runs on Raspberry Pi OS. On a laptop, `pip install -r requirements.raspi.txt` fails while compiling it.

For development use the mock requirements, which skip `RPi.GPIO`:

```sh
pip install --upgrade -r requirements.mock.txt
python main.py start --driver mock
```

The `mock` driver only records the duty and never touches hardware. The `auto` and `rpigpio` drivers deliberately do **not** fall back to it: on a board where the GPIO library cannot be loaded, `pifanctl start` exits with an error instead of looking healthy while the fan stays uncontrolled.

## Runtime: the controller exits with "Cannot drive the fan"

- `RPi.GPIO is not usable here`: the container or process has no access to GPIO. In Docker use `--privileged --user 0` (the image runs as a non-root user, and `RPi.GPIO` needs `/dev/mem`); in Kubernetes the chart's controller already runs privileged. On a Raspberry Pi 5 `RPi.GPIO` does not work, use `--driver sysfs` (or leave `--driver auto`).
- `/sys/class/pwm/pwmchip0 does not exist`: the kernel PWM overlay is not enabled. Add `dtoverlay=pwm-2chan` to `/boot/firmware/config.txt` and reboot.

## Runtime: the fan keeps switching on and off

If the fan duty swings between low values and the fan starts and stops every minute or so, the hottest node is sitting just above `--temp-low`: the fan cools it under the start temperature, stops, and the node heats up again.

- Make sure the temperature hysteresis is on (`--temp-hysteresis`, default 5 °C; the chart value is `curve.hysteresis`). `0` turns it off. With it on, the fan keeps running until the temperature is 5 °C under its peak, so each cycle is much longer. [Temperature hysteresis](hysteresis.md) shows it on a graph and explains how to choose the value.
- If the node still hovers just above the start temperature, lower `--temp-low` a few degrees. The fan then runs continuously at a low duty instead of cycling.

## Runtime: the fan ignores a hot neighbour

Check `pifanctl_control_source` (or the dashboard's "Where the controller got its temperature" panel). `local` means the controller could not reach Prometheus and only sees its own node. `failsafe` means no temperature could be read at all, and the fan is held at the failsafe duty.
