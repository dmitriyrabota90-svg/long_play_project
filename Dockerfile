FROM python:3.12-slim

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e . \
    && groupadd --gid "${APP_GID}" appuser \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home appuser \
    && mkdir -p /app/data/raw /app/data/exports /app/logs \
    && chown -R appuser:appuser /app

USER appuser

CMD ["python", "scripts/run_scheduler.py"]
