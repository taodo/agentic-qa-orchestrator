# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src
# Public mode label only; no credentials or runtime environment enter the bundle.
ENV PUBLIC_QA_SENTINEL_MODE=preview-demo
RUN npm run build

FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3 AS package
WORKDIR /build
COPY pyproject.toml constraints-preview.txt ./
COPY src ./src
COPY alembic ./alembic
RUN python -m pip install --no-cache-dir setuptools==84.0.0 \
    && python -m pip install --no-cache-dir --no-build-isolation --constraint constraints-preview.txt --prefix /install .

FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=package /install /usr/local
COPY --from=frontend /build/frontend/dist /app/frontend/dist
RUN groupadd --gid 10001 sentinel && useradd --uid 10001 --gid sentinel --no-create-home sentinel \
    && mkdir -p /tmp/qa-sentinel /var/data/qa-sentinel \
    && chown sentinel:sentinel /tmp/qa-sentinel /var/data/qa-sentinel \
    && chmod 0700 /var/data/qa-sentinel
USER 10001:10001
EXPOSE 10000
CMD ["python", "-m", "qa_sentinel.host.container"]
