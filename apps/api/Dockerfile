FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app/apps/api
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev
COPY apps/api /app/apps/api
COPY services /app/services
ENV PATH="/app/apps/api/.venv/bin:$PATH"
CMD ["uvicorn", "factory.api:app", "--host", "0.0.0.0", "--port", "8000"]
