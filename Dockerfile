FROM python:3.13-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin appuser
COPY pyproject.toml requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY --chown=appuser:appuser . .
RUN mkdir -p runs artifacts logs reports && chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python scripts/docker_healthcheck.py

CMD ["python", "main.py"]
