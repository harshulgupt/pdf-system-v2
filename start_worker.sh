#!/usr/bin/env bash
set -e

echo "Starting PDF processing worker..."
exec python -m app.worker
