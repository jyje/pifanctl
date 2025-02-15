<div align="center">

# pifanctl

<img alt="pifanctl logo" src="docs/whale-cooling-pie.jpg" height="250" style="max-width: 100%;">

🥧 A CLI for **PWM Fan Controlling** of **Raspberry Pi**

[![CI status for main branch](https://github.com/jyje/pifanctl/actions/workflows/build-image-main.yaml/badge.svg?branch=main)](https://github.com/jyje/pifanctl/actions/workflows/build-image-main.yaml)
[![CI status for develop branch](https://github.com/jyje/pifanctl/actions/workflows/build-image-develop.yaml/badge.svg?branch=develop)](https://github.com/jyje/pifanctl/actions/workflows/build-image-develop.yaml)
[![GitHub Repo stars](https://img.shields.io/github/stars/jyje/pifanctl?style=flat&color=yellow)](https://github.com/jyje/pifanctl)


</div>

🐳 **pifanctl** is a CLI tool for PWM fan control on Raspberry Pi. It can be easily run via **Docker** and **Kubernetes** and is optimized for ARM64 architecture. The project features a CI/CD pipeline using GitHub Actions with Actions Runner Controller (ARC), ensuring all builds are tested in actual Raspberry Pi environments. Please enjoy it!

## 1. Run

You should access the Raspberry Pi (ARM64) to run the following commands.

### 1.1. Run using Docker

```sh
docker run -i ghcr.io/jyje/pifanctl:latest python main.py --help
```

### 1.2. Run using Source

```sh
git clone https://github.com/jyje/pifanctl ~/.pifanctl
cd ~/.pifanctl/sources
pip install --upgrade -r requirements.raspi.txt
python ~/.pifanctl/sources/main.py --help
```

Then you can use the following command to control the fan:

![result of `pifanctl --help`](docs/pifanctl-help.png)

## 2. Build

If you want to build it yourself, you can do the following:

> [!IMPORTANT]
> The package `RPi.GPIO` is available on the Raspberry Pi OS or Linux OS tuned by Raspberry Pi Foundation. So you should run following command on Raspberry Pi.

```sh
git clone https://github.com/jyje/pifanctl ~/.pifanctl
cd ~/.pifanctl/sources
pip install --upgrade -r requirements.raspi.txt
```

Then you can debug the source code with the following command:

```sh
python ~/.pifanctl/sources/main.py --help
python ~/.pifanctl/sources/main.py --version
python ~/.pifanctl/sources/main.py status
```

## 3. CI/CD Pipeline

This project uses GitHub Actions with Actions Runner Controller (ARC) for ARM64-based CI/CD pipeline. The builds are executed on self-hosted Raspberry Pi runners, ensuring native ARM64 compatibility.

### 3.1. Workflow Structure

- **Main Branch (`build-image-main.yaml`)**
  - Builds and publishes to `ghcr.io/jyje/pifanctl:latest`
  - Tags with commit SHA
  - Runs on production-ready code

- **Develop Branch (`build-image-develop.yaml`)**
  - Builds and publishes to `ghcr.io/jyje/pifanctl-dev:latest`
  - Used for development and testing

- **Issue Branches (`build-image-issue.yaml`)**
  - Builds and publishes to `ghcr.io/jyje/pifanctl-issue:latest`
  - Builds feature branches with pattern `issue-**`
  - Tags only with commit SHA for temporary testing

### 3.2. Key Features

- Native ARM64 builds using self-hosted runners (`r4spi-microk8s`)
- Automatic version tagging using commit SHA
- Skip CI option with `--no-ci` flag in commit messages
- GitHub Container Registry (ghcr.io) integration
- Automated testing of built images

### 3.3. Build Process

1. Initialize and check for CI skip flag
2. Build Docker image for ARM64 platform
3. Push to GitHub Container Registry
4. Run automated tests on the built image



## 4. Trouble Shooting

Is there any problem? see [trouble-shooting.md](docs/trouble-shooting.md)

## 5. References

- [Official: Raspberry Pi Foundation](https://www.raspberrypi.org)
- [Blog: Using Raspberry Pi to Control a PWM Fan and Monitor its Speed](https://blog.driftking.tw/en/2019/11/Using-Raspberry-Pi-to-Control-a-PWM-Fan-and-Monitor-its-Speed/)
