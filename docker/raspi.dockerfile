# syntax=docker/dockerfile:1
# Same image as all.dockerfile, built from the Raspberry Pi requirements only.

FROM python:3.14-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY ./sources/requirements.*.txt /tmp/requirements/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements/requirements.raspi.txt


FROM python:3.14-slim AS runner

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /opt/venv /opt/venv
COPY ./sources/ /workspace
WORKDIR /workspace

RUN useradd --system --uid 10001 --no-create-home pifanctl
USER 10001

CMD ["python", "main.py", "--help"]
