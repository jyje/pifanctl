# 문제 해결

[English](trouble-shooting.md) | **한국어**

## 빌드: externally-managed-environment

라즈베리 파이에서 다음 오류가 나면:

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

다음 명령을 시도해 보세요:

```sh
python3 -m venv ~/.pifanctl/sources/venv
source ~/.pifanctl/sources/venv/bin/activate

pip install --upgrade -r requirements.raspi.txt

# 가상 환경을 비활성화하려면:
# deactivate
```

## 빌드: 라즈베리 파이가 아닌 머신에서 RPi.GPIO

`RPi.GPIO`는 라즈베리 파이 OS에서만 빌드되고 실행됩니다. 노트북에서 `pip install -r requirements.raspi.txt`를 하면 컴파일 단계에서 실패합니다.

개발에는 `RPi.GPIO`를 건너뛰는 mock requirements를 쓰세요.

```sh
pip install --upgrade -r requirements.mock.txt
python main.py start --driver mock
```

`mock` 드라이버는 duty만 기록하고 하드웨어를 건드리지 않습니다. `auto`와 `rpigpio` 드라이버는 의도적으로 mock으로 **폴백하지 않습니다**. GPIO 라이브러리를 불러올 수 없는 보드에서는 팬이 제어되지 않는데 정상처럼 보이는 대신 `pifanctl start`가 오류로 종료됩니다.

## 실행: 컨트롤러가 "Cannot drive the fan"으로 종료

- `RPi.GPIO is not usable here`: 컨테이너나 프로세스가 GPIO에 접근할 수 없습니다. Docker에서는 `--privileged --user 0`을 쓰세요(이미지는 non-root 사용자로 실행되고 `RPi.GPIO`는 `/dev/mem`이 필요합니다). Kubernetes에서는 차트의 컨트롤러가 이미 privileged로 실행됩니다. 라즈베리 파이 5에서는 `RPi.GPIO`가 동작하지 않으므로 `--driver sysfs`(또는 `--driver auto`)를 쓰세요.
- `/sys/class/pwm/pwmchip0 does not exist`: 커널 PWM 오버레이가 꺼져 있습니다. `/boot/firmware/config.txt`에 `dtoverlay=pwm-2chan`을 추가하고 재부팅하세요.

## 실행: 팬이 뜨거운 이웃 노드를 무시함

`pifanctl_control_source`(또는 대시보드의 "Where the controller got its temperature" 패널)를 확인하세요. `local`은 컨트롤러가 Prometheus에 닿지 못해 자기 노드만 본다는 뜻이고, `failsafe`는 온도를 전혀 읽지 못해 팬이 failsafe duty로 고정되었다는 뜻입니다.
