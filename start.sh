#!/usr/bin/env bash

set -e

# Kick off the detached daemon worker
echo "Starting independent Background Queue Worker..."
python -m app.worker &

# Kick off the primary HTTP server and freeze execution into foreground
echo "Starting primary Uvicorn API server..."
exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
