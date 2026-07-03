# syntax=docker/dockerfile:1
#
# fdp-mcp image — multi-stage uv build into a self-contained venv, copied into a
# slim, non-root runtime. Serves the streamable-HTTP MCP transport; point it at
# a FAIR Data Point with FDP_BASE_URL. Mirrors the server repo's Dockerfile
# conventions (uv builder + slim non-root runtime).

# --- builder: resolve + install deps and the project into /app/.venv ---------
FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependency layer first so it caches unless pyproject/uv.lock change. README.md
# is referenced by pyproject (project.readme) and is needed to build the project.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Project sources, then install the project itself.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- runtime: slim image with just the venv + app, run as non-root -----------
FROM python:3.12-slim AS runtime

RUN groupadd --system fdpmcp \
    && useradd --system --gid fdpmcp --home-dir /app --no-create-home fdpmcp

WORKDIR /app
COPY --from=builder --chown=fdpmcp:fdpmcp /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    FDP_MCP_TRANSPORT=streamable-http \
    FDP_MCP_HOST=0.0.0.0 \
    FDP_MCP_PORT=8000

USER fdpmcp
EXPOSE 8000

# FDP_BASE_URL is the one required setting; provide it at `docker run` time:
#   docker run -e FDP_BASE_URL=https://fdp.example.org <image>
# HEALTHCHECK is added in task 0.2 once the server exposes a liveness endpoint.
ENTRYPOINT ["fdp-mcp"]
