# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.14

FROM python:${PYTHON_VERSION}-slim AS builder

# gcc is only needed to compile RPi.GPIO. It stays in this stage.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY ./sources/requirements.*.txt /tmp/requirements/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements/requirements.all.txt


FROM python:${PYTHON_VERSION}-slim AS runner

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /opt/venv /opt/venv
COPY ./sources/ /workspace
WORKDIR /workspace

# Runs unprivileged by default, which is enough for `agent` and `status`.
# Driving GPIO or /sys/class/pwm needs more: the Helm chart's controller runs
# as root with the access it needs, and `docker run --privileged` does the same.
RUN useradd --system --uid 10001 --no-create-home pifanctl
USER 10001

CMD ["python", "main.py", "--help"]
