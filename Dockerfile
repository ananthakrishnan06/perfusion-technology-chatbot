# Production Dockerfile for PerfusionGPT on Google Cloud Run
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Prevent Python from writing .pyc files and enable unbuffered output for real-time Cloud Run logging
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

# Install minimal system dependencies (curl for healthchecks, build-essential for wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy codebase and pre-built vector indices
COPY . .

# Ensure storage directories exist
RUN mkdir -p data/documents data/indices

# Expose default Cloud Run port
EXPOSE 8080

# Built-in health check for container liveness
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/api/v1/health || exit 1

# Launch Uvicorn bound to dynamic $PORT injected by Cloud Run
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
