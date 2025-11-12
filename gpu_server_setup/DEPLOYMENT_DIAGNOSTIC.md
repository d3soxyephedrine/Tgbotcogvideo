# GPU Server Deployment Diagnostic Guide

## Current Issue
The CogVideoX FastAPI video service at `http://proxy.us-ca-6.gpu-instance.novita.ai:8082` is not responding.

## Quick Diagnosis

### 1. Check GPU Server Status
SSH into your GPU server and run:

```bash
# Check if the service is running
sudo systemctl status video-api

# Check service logs
sudo journalctl -u video-api -n 50 --no-pager

# Check if the port is listening
sudo netstat -tlnp | grep 8080

# Check process
ps aux | grep uvicorn
```

### 2. Test Local Connectivity
From the GPU server itself:

```bash
# Health check
curl http://localhost:8080/health

# If using port 8082, try:
curl http://localhost:8082/health
```

### 3. Check Port Configuration

**IMPORTANT:** There's a port mismatch!

- **Current Telegram Bot Config**: `VIDEO_API_URL=http://proxy.us-ca-6.gpu-instance.novita.ai:8082`
- **GPU Server Default**: Runs on port 8080

**Fix Option 1: Update Telegram Bot to use port 8080**
```bash
# In Replit, update the environment variable
VIDEO_API_URL=http://proxy.us-ca-6.gpu-instance.novita.ai:8080
```

**Fix Option 2: Change GPU Server to use port 8082**
```bash
# On GPU server, edit the service file
sudo nano /etc/systemd/system/video-api.service

# Change line 11 from:
ExecStart=/home/ubuntu/cvxenv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
# To:
ExecStart=/home/ubuntu/cvxenv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8082

# Then reload and restart
sudo systemctl daemon-reload
sudo systemctl restart video-api
```

## Common Deployment Issues

### Service Not Running
```bash
# Start the service
sudo systemctl start video-api

# Enable auto-start on boot
sudo systemctl enable video-api

# Restart if already running
sudo systemctl restart video-api
```

### Port Already in Use
```bash
# Find what's using the port
sudo lsof -i :8080
# or
sudo lsof -i :8082

# Kill the process if needed
sudo kill -9 <PID>
```

### Model Not Loading (CUDA Issues)
```bash
# Check CUDA is available
python3 -c "import torch; print(torch.cuda.is_available())"

# Check GPU status
nvidia-smi

# If CUDA not available, check the logs
sudo journalctl -u video-api -n 100 --no-pager
```

### Network/Firewall Issues
```bash
# Check if firewall is blocking
sudo ufw status

# Allow port 8080 or 8082
sudo ufw allow 8080
# or
sudo ufw allow 8082
```

## Quick Restart Sequence

If everything is configured correctly but not working:

```bash
# SSH into GPU server
ssh ubuntu@proxy.us-ca-6.gpu-instance.novita.ai

# Restart the service
sudo systemctl restart video-api

# Wait 30 seconds for model to load
sleep 30

# Test health endpoint
curl http://localhost:8080/health

# Check logs
sudo journalctl -u video-api -n 20 --no-pager
```

## Verify API Key Match

Make sure the API keys match:

**On GPU Server (.env file):**
```bash
cat /home/ubuntu/video_api/.env | grep API_SECRET
```

**On Replit (Telegram Bot):**
```bash
echo $VIDEO_API_KEY
```

These MUST match exactly!

## Test from Telegram Bot Server

From Replit, test connectivity:

```bash
# Test health endpoint
curl -v http://proxy.us-ca-6.gpu-instance.novita.ai:8080/health

# Test with API key
curl -v http://proxy.us-ca-6.gpu-instance.novita.ai:8080/generate_video \
  -H "Content-Type: application/json" \
  -H "x-api-key: $VIDEO_API_KEY" \
  -d '{"prompt": "test", "frames": 16, "fps": 8, "steps": 20}'
```

## Next Steps

1. **SSH into GPU server**: `ssh ubuntu@proxy.us-ca-6.gpu-instance.novita.ai`
2. **Check service status**: `sudo systemctl status video-api`
3. **Fix port mismatch**: Either update `VIDEO_API_URL` on Replit or change port on GPU server
4. **Restart service**: `sudo systemctl restart video-api`
5. **Test connectivity**: `curl http://localhost:8080/health`
6. **Update Telegram bot** if port changed

## Emergency: Manual Start

If systemd service isn't working, manually start the server:

```bash
# SSH into GPU server
cd /home/ubuntu/video_api
source ~/cvxenv/bin/activate

# Load environment
export $(cat .env | xargs)

# Start manually
uvicorn app.main:app --host 0.0.0.0 --port 8080

# Keep terminal open - this will run in foreground
```
