ARG BASE_IMAGE=ghcr.io/jyje/pifanctl@sha256:59060b5b7bc014543ed2db96a914b0b07c1850b99eb4a54bd95dc15d74baad70
FROM ${BASE_IMAGE}
COPY tests/runtime_lab/sitecustomize.py /runtime-lab/sitecustomize.py
ENV PYTHONPATH=/runtime-lab:/workspace PIFANCTL_RUNTIME_LAB=1
LABEL pifanctl.runtime-lab="simulated-io-only-not-for-production"
