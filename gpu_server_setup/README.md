# GPU Server Setup Files

**⚠️ IMPORTANT: These files are NOT part of the Replit bot codebase!**

This directory contains reference files for deploying the CogVideoX-5B video generation service on your **remote Ubuntu GPU server**.

## What's in this folder:

- `main.py` - FastAPI application for the GPU server
- `.env.example` - Environment variables template  
- `video-api.service` - Systemd service file
- `requirements.txt` - Python dependencies for GPU server
- `deploy.sh` - Automated deployment script
- `SETUP_GUIDE.md` - Complete setup instructions

## Deployment Location:

These files should be deployed to: **`/home/ubuntu/video_api/`** on your Ubuntu GPU server.

## Quick Start:

1. Copy files to your GPU server (via scp or git)
2. Follow instructions in `SETUP_GUIDE.md`
3. After setup, update Replit bot environment variables:
   - `COGVIDEOX_API_URL`: http://YOUR_GPU_SERVER_IP:8080/generate_video
   - `COGVIDEOX_API_KEY`: (matches API_SECRET from .env)

## Integration:

The Telegram bot (running on Replit) will call your GPU server's API via HTTP.
The integration code has been added to `llm_api.py` and `telegram_handler.py`.
