FROM ghcr.io/astral-sh/uv:0.9.13 AS uv

FROM python:3.13.0-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /var/lib/dom-domych/files \
    && chown -R app:app /app /var/lib/dom-domych
USER app
CMD ["uvicorn", "dom_domych.entrypoints.api:create_app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]
