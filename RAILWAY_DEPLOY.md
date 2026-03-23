# Railway Deployment Guide

## Two services required

This system needs **two separate Railway services** sharing the same environment variables.

### Service 1 — API
- Start command: `bash start.sh`
- This runs Uvicorn only. No PDF processing happens here.

### Service 2 — Worker  
- Start command: `bash start_worker.sh`
- This is the only process that downloads and extracts PDFs.
- Give it **at least 2 GB RAM** in Railway settings (Settings → Resources).
- The API service can stay at 512 MB.

## Why two services?
Processing a 400–500 MB PDF peaks at 300–600 MB of RAM. Running that inside
the API process would OOM-kill the HTTP server for every user. The worker runs
in isolation — if it gets OOM-killed on a very large file, the API keeps
serving and that upload is marked `failed` automatically on the next worker
restart.

## Required environment variables (both services)
```
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
B2_ACCESS_KEY_ID=...
B2_SECRET_ACCESS_KEY=...
B2_ENDPOINT_URL=https://s3.us-west-004.backblazeb2.com
B2_BUCKET_NAME=your-bucket
SECRET_KEY=your-secret
```

## Sharing variables between services
In Railway: create a shared Variable Group and attach it to both services.
