<div align="center">

# pifanctl

<img alt="pifanctl logo" src="docs/whale-cooling-pie.jpg" height="250" style="max-width: 100%;">

🥧 A CLI for **PWM Fan Controlling** of **Raspberry Pi**

[![CI status for main branch](https://github.com/jyje/pifanctl/actions/workflows/build-image-main.yaml/badge.svg?branch=main)](https://github.com/jyje/pifanctl/actions/workflows/build-image-main.yaml)
[![CI status for develop branch](https://github.com/jyje/pifanctl/actions/workflows/build-image-develop.yaml/badge.svg?branch=develop)](https://github.com/jyje/pifanctl/actions/workflows/build-image-develop.yaml)
[![GitHub Repository stars](https://img.shields.io/github/stars/jyje/pifanctl)](https://github.com/jyje/pifanctl)

</div>

# Build

If you want to build it yourself, you can do the following:

> [!IMPORTANT]
> The package `RPi.GPIO` is available on the Raspberry Pi OS or Linux OS tuned by Raspberry Pi Foundation. So you should run following command on Raspberry Pi.

```sh
git clone https://github.com/jyje/pifanctl ~/.pifanctl
cd ~/.pifanctl/sources
pip install --upgrade -r requirements.raspi.txt
python ~/.pifanctl/sources/main.py --help
```

Then you can use the following command to control the fan:

![result of `pifanctl --help`](docs/pifanctl-help.png)

### Trouble Shooting

#### Problem 1: externally-managed-environment
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

#### Problem 2: Mock.GPIO

In non-Raspberry Pi OS, if you encounter like the following error:

```sh
Building wheels for collected packages: RPi.GPIO
  Building wheel for RPi.GPIO (pyproject.toml) ... error
  error: subprocess-exited-with-error
  
  × Building wheel for RPi.GPIO (pyproject.toml) did not run successfully.
  │ exit code: 1
  ╰─> [27 lines of output]
      running bdist_wheel
      running build
      running build_py
      creating build/lib.macosx-15.3-arm64-cpython-313/RPi
      copying RPi/__init__.py -> build/lib.macosx-15.3-arm64-cpython-313/RPi
      creating build/lib.macosx-15.3-arm64-cpython-313/RPi/GPIO
      copying RPi/GPIO/__init__.py -> build/lib.macosx-15.3-arm64-cpython-313/RPi/GPIO
      running build_ext
      building 'RPi._GPIO' extension
      creating build/temp.macosx-15.3-arm64-cpython-313/source
```

This is because the `RPi.GPIO` is not available in non-Raspberry Pi OS. Then we can use `Mock.GPIO` instead to simulate the `RPi.GPIO` to control the fan.

So you can try the following command:

```sh
pip install --upgrade -r requirements.mock.txt
```

---

# References

- [Official: Raspberry Pi Foundation](https://www.raspberrypi.org)
- [Blog: Using Raspberry Pi to Control a PWM Fan and Monitor its Speed](https://blog.driftking.tw/en/2019/11/Using-Raspberry-Pi-to-Control-a-PWM-Fan-and-Monitor-its-Speed/)
