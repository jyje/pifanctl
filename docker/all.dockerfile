# syntax=docker/dockerfile:1

FROM python:3.14-slim AS builder

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


FROM python:3.14-slim AS runner

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /opt/venv /opt/venv
COPY ./sources/ /workspace
WORKDIR /workspace

# Runs unprivileged by default, which is enough for `agent` and `status`.
# Operator-managed workers get the hardware access declared by the operator
# chart. Users manage Fan/CoolingZone CRs instead of starting local controllers.
RUN useradd --system --uid 10001 --no-create-home pifanctl
USER 10001

CMD ["python", "main.py", "--help"]
