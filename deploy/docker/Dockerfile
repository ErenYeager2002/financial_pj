FROM docker.m.daocloud.io/library/python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright \
    PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/app /app/backend/app
RUN sed -i \
        -e 's|deb.debian.org|mirrors.aliyun.com|g' \
        -e 's|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir /app/backend
RUN python -m playwright install-deps chromium
RUN python -m playwright install chromium

COPY frontend/dist /app/frontend/dist
COPY skills /app/skills
COPY scripts /app/scripts

RUN groupadd --system --gid 10001 financial-platform \
    && useradd \
        --system \
        --uid 10001 \
        --gid financial-platform \
        --home-dir /var/lib/financial-platform \
        --shell /usr/sbin/nologin \
        financial-platform \
    && install -d \
        -o financial-platform \
        -g financial-platform \
        -m 0750 \
        /var/lib/financial-platform

USER 10001:10001
WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
