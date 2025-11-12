# CogVideoX GPU Server Setup Guide

Complete guide to deploy the CogVideoX-5B video generation API on your Ubuntu GPU server.

## Prerequisites

- Ubuntu server with NVIDIA GPU
- CUDA installed and working
- Python 3.8+ installed
- Internet connection for model downloads

## Step 1: Upload Files to Server

Copy these files to your server at `/home/ubuntu/video_api/app/`:

```bash
# From your local machine, scp the main.py to the server
scp gpu_server_setup/main.py ubuntu@YOUR_SERVER_IP:/home/ubuntu/video_api/app/main.py
scp gpu_server_setup/requirements.txt ubuntu@YOUR_SERVER_IP:/home/ubuntu/video_api/requirements.txt
scp gpu_server_setup/.env.example ubuntu@YOUR_SERVER_IP:/home/ubuntu/video_api/.env
```

Or manually create the files using `nano` or `vim` on the server.

## Step 2: Install Dependencies

SSH into your server and run:

```bash
cd ~/video_api
source ~/cvxenv/bin/activate
pip install -r requirements.txt
```

## Step 3: Configure Environment

Edit the `.env` file:

```bash
cd ~/video_api
nano .env
```

Update the API_SECRET to a strong random key:

```env
API_SECRET=your-super-secret-key-here-$(openssl rand -hex 32)
MODEL_ID=THUDM/CogVideoX-5b
DEFAULT_FRAMES=16
DEFAULT_FPS=8
DEFAULT_STEPS=20
MAX_FRAMES=49
MAX_STEPS=50
OUTPUT_DIR=/tmp/videos
```

Save and exit (Ctrl+X, Y, Enter in nano).

## Step 4: Test Manually

Before setting up the service, test the API manually:

```bash
cd ~/video_api
source ~/cvxenv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

In another terminal, test it:

```bash
# Health check
curl http://localhost:8080/health

# Generate a test video
curl -X POST http://localhost:8080/generate_video \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-super-secret-key-here" \
  -d '{
    "prompt": "A test video of a dragon flying over a neon city",
    "frames": 16,
    "fps": 8,
    "steps": 20
  }'
```

If it works, press Ctrl+C to stop the server.

## Step 5: Set Up Systemd Service

Copy the service file:

```bash
sudo cp ~/video_api/../gpu_server_setup/video-api.service /etc/systemd/system/video-api.service
```

Or create it manually:

```bash
sudo nano /etc/systemd/system/video-api.service
```

Paste the contents from `video-api.service` and save.

**Important**: Make sure the `.env` file path in the service file matches your setup:
```
EnvironmentFile=/home/ubuntu/video_api/.env
```

## Step 6: Enable and Start Service

```bash
# Reload systemd to recognize the new service
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable video-api

# Start the service now
sudo systemctl start video-api

# Check status
sudo systemctl status video-api
```

Expected output:
```
● video-api.service - CogVideoX Video Generation API
     Loaded: loaded (/etc/systemd/system/video-api.service; enabled)
     Active: active (running) since ...
```

## Step 7: Monitor Logs

View logs in real-time:

```bash
# Combined output
sudo journalctl -u video-api -f

# Standard output only
sudo tail -f /var/log/video-api.log

# Error output only
sudo tail -f /var/log/video-api-error.log
```

## Step 8: Test the Service

```bash
# Health check
curl http://YOUR_SERVER_IP:8080/health

# Generate video
curl -X POST http://YOUR_SERVER_IP:8080/generate_video \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-super-secret-key-here" \
  -d '{
    "prompt": "A cinematic shot of a spaceship landing on Mars",
    "frames": 16,
    "fps": 8,
    "steps": 20
  }'
```

## Common Commands

```bash
# Start service
sudo systemctl start video-api

# Stop service
sudo systemctl stop video-api

# Restart service
sudo systemctl restart video-api

# Check status
sudo systemctl status video-api

# View logs
sudo journalctl -u video-api -f

# Disable auto-start
sudo systemctl disable video-api

# Re-enable auto-start
sudo systemctl enable video-api

# Check if service is enabled
sudo systemctl is-enabled video-api
```

## Troubleshooting

### Service won't start

Check logs:
```bash
sudo journalctl -u video-api -n 100 --no-pager
```

Common issues:
- Wrong Python path in service file
- Missing dependencies in virtualenv
- Incorrect .env file path
- Port 8080 already in use

### CUDA errors

Verify CUDA is working:
```bash
nvidia-smi
python -c "import torch; print(torch.cuda.is_available())"
```

### Model download issues

The first run will download ~10GB model files. Ensure:
- Sufficient disk space
- Internet connection
- HuggingFace access (may need `huggingface-cli login`)

### Permission errors

Fix log file permissions:
```bash
sudo touch /var/log/video-api.log /var/log/video-api-error.log
sudo chown ubuntu:ubuntu /var/log/video-api*.log
```

## Security Notes

1. **API Key**: Use a strong random key, never commit to git
2. **Firewall**: Only expose port 8080 to trusted IPs if possible
3. **HTTPS**: Consider putting nginx in front with SSL for production
4. **Rate Limiting**: Add rate limiting to prevent abuse

## Next Steps

Once the service is running:
1. Note your server's IP address
2. Save the API_SECRET securely
3. Update your Telegram bot to call this endpoint
4. Consider adding nginx reverse proxy for SSL
5. Set up monitoring/alerting

## Testing from Telegram Bot

Update your Telegram bot's `COGVIDEOX_API_URL` to:
```
http://YOUR_SERVER_IP:8080/generate_video
```

And `COGVIDEOX_API_KEY` to match your API_SECRET.
