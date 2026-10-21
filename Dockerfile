# CodeMind AI - Production Dockerfile
FROM python:3.12-slim

# Set environment flags
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production

# Install essential system dependencies and curl for health probes
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root application user and group for container security
RUN groupadd -g 1001 codemind && \
    useradd -u 1001 -g codemind -m -s /bin/bash codemind

WORKDIR /app

# Copy dependency definition and install
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /app/backend/requirements.txt

# Copy application directories
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY alembic.ini /app/alembic.ini

# Ensure storage directories exist and have proper ownership
RUN mkdir -p /app/storage/uploaded_repos /app/backend/data && \
    chown -R codemind:codemind /app

# Switch to non-root execution
USER codemind

# Expose HTTP API port
EXPOSE 8000

# Container liveness health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Production startup
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
