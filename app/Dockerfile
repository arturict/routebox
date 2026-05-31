FROM python:3.12-alpine

RUN apk add --no-cache openssh-client bash ca-certificates

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static/ static/

ENV PORT=81 \
    BACKEND=local \
    CONFIG_PATH=/config/dynamic.yml \
    STATE_FILE=/data/state.json \
    BACKUP_DIR=/data/backups \
    ENV_FILE=/data/settings.env \
    APP_NAME="RouteBox"

EXPOSE 81

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"81\")}/api/health', timeout=5)" || exit 1

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-81} --workers ${WEB_CONCURRENCY:-1} --threads ${WEB_THREADS:-4} --timeout ${WEB_TIMEOUT:-90} app:app"]
