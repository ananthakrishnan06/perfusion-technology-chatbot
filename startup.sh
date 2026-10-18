#!/bin/bash
# Startup script for PerfusionGPT on Azure App Service
# Ensures dynamic PORT binding and production worker startup

PORT="${PORT:-8000}"
echo "Starting PerfusionGPT backend on port ${PORT}..."

# Start uvicorn with production binding
python -m uvicorn main:app --host 0.0.0.0 --port "${PORT}"
