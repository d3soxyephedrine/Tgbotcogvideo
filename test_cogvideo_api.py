#!/usr/bin/env python3
"""
Test script for CogVideoX GPU API
Run this to debug HTTP 422 errors
"""
import os
import sys
import requests
import json
from dotenv import load_dotenv

# Load environment
load_dotenv()
COGVIDEOX_API_URL = os.environ.get("COGVIDEOX_API_URL")
COGVIDEOX_API_KEY = os.environ.get("COGVIDEOX_API_KEY")

print("=" * 60)
print("CogVideoX API Test Script")
print("=" * 60)
print(f"API URL: {COGVIDEOX_API_URL}")
print(f"API Key: {'*' * 20 if COGVIDEOX_API_KEY else 'NOT SET'}")
print()

if not COGVIDEOX_API_URL or not COGVIDEOX_API_KEY:
    print("❌ Error: COGVIDEOX_API_URL or COGVIDEOX_API_KEY not set")
    print("Please set these in your .env file")
    sys.exit(1)

# Test payload
payload = {
    "prompt": "A cat playing with a ball",
    "frames": 16,
    "fps": 8,
    "steps": 20
}

print("Test payload:")
print(json.dumps(payload, indent=2))
print()

headers = {
    "Content-Type": "application/json",
    "x-api-key": COGVIDEOX_API_KEY
}

print("Sending request...")
print()

try:
    response = requests.post(
        COGVIDEOX_API_URL,
        json=payload,
        headers=headers,
        timeout=10  # Short timeout for testing
    )

    print(f"Status Code: {response.status_code}")
    print()

    if response.status_code == 200:
        print("✅ Success!")
        result = response.json()
        print(json.dumps(result, indent=2))
    elif response.status_code == 422:
        print("❌ Validation Error (422)")
        print()
        print("Raw response:")
        print(response.text)
        print()
        try:
            error_detail = response.json()
            print("Parsed error:")
            print(json.dumps(error_detail, indent=2))

            # Try to extract specific validation errors
            if isinstance(error_detail, dict) and 'detail' in error_detail:
                detail = error_detail['detail']
                if isinstance(detail, list):
                    print()
                    print("Validation errors:")
                    for err in detail:
                        field = err.get('loc', ['unknown'])[-1]
                        msg = err.get('msg', 'Unknown error')
                        print(f"  - {field}: {msg}")
        except:
            pass
    else:
        print(f"❌ HTTP Error {response.status_code}")
        print(response.text)

except requests.exceptions.ConnectionError as e:
    print("❌ Connection Error")
    print(f"Cannot connect to {COGVIDEOX_API_URL}")
    print(f"Error: {e}")
    print()
    print("Possible causes:")
    print("  - GPU server is not running")
    print("  - URL is incorrect")
    print("  - Firewall blocking connection")

except requests.exceptions.Timeout:
    print("❌ Timeout")
    print("Request timed out after 10 seconds")

except Exception as e:
    print(f"❌ Error: {type(e).__name__}")
    print(str(e))

print()
print("=" * 60)
