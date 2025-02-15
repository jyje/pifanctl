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

## Build: Mock.GPIO

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
Simulating the `RPi.GPIO` is not proper way to control the fan. It is only for UX enhancement.

So you can try the following command:

```sh
pip install --upgrade -r requirements.mock.txt
```
