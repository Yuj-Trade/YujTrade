FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin appuser
COPY pyproject.toml requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY --chown=appuser:appuser . .
USER appuser

CMD ["python", "main.py"]
