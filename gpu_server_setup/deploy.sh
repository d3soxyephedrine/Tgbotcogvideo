#!/bin/bash
# Quick deployment script for CogVideoX GPU Server

set -e

echo "🚀 CogVideoX GPU Server Deployment"
echo "=================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running on Ubuntu server
if [ ! -f /etc/os-release ]; then
    echo -e "${RED}❌ This script is designed for Ubuntu servers${NC}"
    exit 1
fi

# Step 1: Copy service file
echo -e "\n${YELLOW}Step 1: Installing systemd service...${NC}"
if [ -f "video-api.service" ]; then
    sudo cp video-api.service /etc/systemd/system/video-api.service
    echo -e "${GREEN}✓ Service file copied${NC}"
else
    echo -e "${RED}❌ video-api.service not found in current directory${NC}"
    exit 1
fi

# Step 2: Reload systemd
echo -e "\n${YELLOW}Step 2: Reloading systemd...${NC}"
sudo systemctl daemon-reload
echo -e "${GREEN}✓ Systemd reloaded${NC}"

# Step 3: Enable service
echo -e "\n${YELLOW}Step 3: Enabling service...${NC}"
sudo systemctl enable video-api
echo -e "${GREEN}✓ Service enabled${NC}"

# Step 4: Start service
echo -e "\n${YELLOW}Step 4: Starting service...${NC}"
sudo systemctl start video-api
echo -e "${GREEN}✓ Service started${NC}"

# Step 5: Check status
echo -e "\n${YELLOW}Step 5: Checking status...${NC}"
sleep 2
if sudo systemctl is-active --quiet video-api; then
    echo -e "${GREEN}✅ Service is running!${NC}"
    sudo systemctl status video-api --no-pager -l
else
    echo -e "${RED}❌ Service failed to start${NC}"
    echo -e "${YELLOW}Showing last 20 log lines:${NC}"
    sudo journalctl -u video-api -n 20 --no-pager
    exit 1
fi

# Step 6: Test endpoint
echo -e "\n${YELLOW}Step 6: Testing health endpoint...${NC}"
sleep 3
if curl -f http://localhost:8080/health 2>/dev/null; then
    echo -e "\n${GREEN}✅ API is responding!${NC}"
else
    echo -e "\n${YELLOW}⚠ API not responding yet (may still be loading model)${NC}"
    echo -e "${YELLOW}Check logs: sudo journalctl -u video-api -f${NC}"
fi

echo -e "\n${GREEN}=================================="
echo -e "✅ Deployment Complete!${NC}"
echo -e "==================================\n"
echo -e "${YELLOW}Useful commands:${NC}"
echo "  sudo systemctl status video-api    # Check status"
echo "  sudo systemctl restart video-api   # Restart service"
echo "  sudo journalctl -u video-api -f    # View logs"
echo "  curl http://localhost:8080/health  # Test API"
