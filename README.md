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

---

# Trouble Shooting

Is there any problem? see [trouble-shooting.md](docs/trouble-shooting.md)

---

# References

- [Official: Raspberry Pi Foundation](https://www.raspberrypi.org)
- [Blog: Using Raspberry Pi to Control a PWM Fan and Monitor its Speed](https://blog.driftking.tw/en/2019/11/Using-Raspberry-Pi-to-Control-a-PWM-Fan-and-Monitor-its-Speed/)
