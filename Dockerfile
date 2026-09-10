FROM node:22-alpine AS webapp
WORKDIR /webapp
COPY webapp/package.json webapp/package-lock.json* ./
RUN npm install
COPY webapp/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ARG GIT_SHA=unknown

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_GIT_SHA=${GIT_SHA}

WORKDIR /app

RUN groupadd --system lab21 && useradd --system --gid lab21 --home-dir /app lab21

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts/docker-entrypoint.sh /docker-entrypoint.sh

COPY --from=webapp /src/lab21_bot/miniapp/static ./src/lab21_bot/miniapp/static

RUN pip install . \
    && mkdir -p /app/uploads/products /app/uploads/quests /app/uploads/memes \
    && chown -R lab21:lab21 /app/uploads \
    && sed -i 's/\r$//' /docker-entrypoint.sh \
    && chmod +x /docker-entrypoint.sh

# Entrypoint starts as root to fix volume ownership, then drops to lab21.
ENTRYPOINT ["/docker-entrypoint.sh"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD ["python", "-m", "lab21_bot.health"]

CMD ["sh", "-c", "alembic upgrade head && exec lab21-bot"]
