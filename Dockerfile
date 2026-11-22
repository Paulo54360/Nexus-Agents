# syntax=docker/dockerfile:1

# --- Stage 1: Node.js 22 LTS runtime for stdio MCP servers (Notion, Gmail, Calendar) ---
FROM node:22-bookworm-slim AS node-base

# --- Stage 2: Build Python dependencies with uv ---
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN uv venv /app/.venv && \
    uv pip install --python /app/.venv/bin/python .

# --- Stage 3: Minimal runtime image (Python 3.12 + Node 22 + non-root user) ---
FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NPM_CONFIG_CACHE=/tmp/.npm

# Copy Node.js 22 + npm/npx for MCP servers
COPY --from=node-base /usr/local/bin/node /usr/local/bin/node
COPY --from=node-base /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Create non-root user for security best practice
RUN groupadd --system nexus && \
    useradd --system --gid nexus --create-home nexus

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --chown=nexus:nexus src ./src
COPY --chown=nexus:nexus config ./config

USER nexus

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "nexus.interfaces.api:app", "--host", "0.0.0.0", "--port", "8000"]
