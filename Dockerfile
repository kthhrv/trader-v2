# ==========================================
# Stage 1: Builder
# ==========================================
FROM python:3.12-slim AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    nodejs \
    npm \
    unzip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# --- Python Dependencies ---
COPY pyproject.toml uv.lock ./
# Install dependencies into .venv (no project root yet)
RUN uv sync --frozen --no-install-project

# --- Node.js Dependencies ---
COPY app/adapters/js/package.json app/adapters/js/package-lock.json ./app/adapters/js/
RUN cd app/adapters/js && npm install --omit=dev

# ==========================================
# Stage 2: Runtime
# ==========================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RUNNING_IN_DOCKER=true \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install ONLY Node.js runtime (no npm)
RUN apt-get update && apt-get install -y \
    nodejs \
    unzip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create directories for mounts
RUN mkdir -p logs data

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy Node.js modules from builder
COPY --from=builder /app/app/adapters/js/node_modules /app/app/adapters/js/node_modules

# Copy application code
COPY . .

# Receive Git Commit SHA from build args
ARG GIT_COMMIT_SHA
ENV GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

# Expose ports
EXPOSE 8000

# Default command
# We use the python executable from the venv directly
CMD ["python", "main.py", "--scheduler"]
