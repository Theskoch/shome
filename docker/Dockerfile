# Build context is the project root; build via docker/docker-compose.yml.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY docker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Application code only. Config lives in /config and state in /data,
# both bind-mounted from the host so they survive rebuilds.
COPY app.py iisstart.htm login.htm css.css ./
COPY assets ./assets

ENV SHOME_APP_DATA_DIR=/data/App_Data \
    SHOME_UPLOADS_DIR=/data/uploads \
    SHOME_LDAP_CONFIG=/config/ldap_config.json

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/login', timeout=4).status == 200 else 1)"

# One worker, several threads: the login throttle counts attempts in process
# memory, so a second worker would silently double the allowance. Threads share
# that memory and are plenty for a home dashboard.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--timeout", "60", "--access-logfile", "-", "app:app"]
