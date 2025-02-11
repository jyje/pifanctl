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
pip install --upgrade -r requirements.txt
python main.py --help
```
### Trouble Shooting

If you encounter the following error:

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

pip install --upgrade -r requirements.txt

# To deactivate the virtual environment, you can run the following command:
# deactivate
```
---
