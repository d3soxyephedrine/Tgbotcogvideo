#!/usr/bin/env python3
"""
GPU Server Connection Diagnostic Tool
Run this to check if the CogVideoX GPU server is accessible
"""
import os
import sys
from video_api import check_video_api_health, VIDEO_API_URL, VIDEO_API_KEY

def main():
    print("=" * 60)
    print("GPU SERVER CONNECTION DIAGNOSTIC")
    print("=" * 60)
    
    # Check environment variables
    print("\n[1] Checking Environment Variables...")
    print(f"   VIDEO_API_URL: {VIDEO_API_URL if VIDEO_API_URL else '❌ NOT SET'}")
    print(f"   VIDEO_API_KEY: {'✓ Set' if VIDEO_API_KEY else '❌ NOT SET'}")
    
    if not VIDEO_API_URL or not VIDEO_API_KEY:
        print("\n❌ CONFIGURATION ERROR: Missing environment variables")
        print("\nPlease set:")
        if not VIDEO_API_URL:
            print("  export VIDEO_API_URL='http://your-gpu-server:8080'")
        if not VIDEO_API_KEY:
            print("  export VIDEO_API_KEY='your-api-key'")
        sys.exit(1)
    
    # Port check
    print("\n[2] Checking Port Configuration...")
    if ':8082' in VIDEO_API_URL:
        print("   ⚠️  WARNING: URL uses port 8082")
        print("   ⚠️  Default GPU server port is 8080")
        print("   ⚠️  This may cause connection issues!")
        print("\n   Fix: Change VIDEO_API_URL to use port 8080, or")
        print("        reconfigure GPU server to listen on port 8082")
    elif ':8080' in VIDEO_API_URL:
        print("   ✓ Port 8080 (correct default port)")
    else:
        print("   ⚠️  No port specified in URL")
    
    # Health check
    print("\n[3] Testing Connection to GPU Server...")
    print(f"   Attempting to reach: {VIDEO_API_URL}/health")
    
    is_healthy, message = check_video_api_health()
    
    if is_healthy:
        print(f"   ✅ SUCCESS: {message}")
        print("\n" + "=" * 60)
        print("✅ GPU SERVER IS ACCESSIBLE AND HEALTHY")
        print("=" * 60)
        print("\nYou can now use /video command in Telegram!")
        return 0
    else:
        print(f"   ❌ FAILED: {message}")
        print("\n" + "=" * 60)
        print("❌ GPU SERVER IS NOT ACCESSIBLE")
        print("=" * 60)
        print("\nTroubleshooting steps:")
        print("1. SSH into GPU server:")
        print(f"   ssh ubuntu@{VIDEO_API_URL.split('//')[1].split(':')[0]}")
        print("\n2. Check if service is running:")
        print("   sudo systemctl status video-api")
        print("\n3. Check service logs:")
        print("   sudo journalctl -u video-api -n 50")
        print("\n4. Restart service:")
        print("   sudo systemctl restart video-api")
        print("\n5. Test locally on GPU server:")
        print("   curl http://localhost:8080/health")
        print("\n6. Check firewall:")
        print("   sudo ufw status")
        print("\nSee gpu_server_setup/DEPLOYMENT_DIAGNOSTIC.md for detailed guide")
        return 1

if __name__ == "__main__":
    sys.exit(main())
