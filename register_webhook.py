#!/usr/bin/env python3
"""
Manual webhook registration script for testing
Usage: python register_webhook.py
"""
import os
import requests

# Get BOT_TOKEN from environment
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ Error: BOT_TOKEN environment variable not set")
    exit(1)

# Get domain (use Railway domain if set, otherwise ko2bot.com)
DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "ko2bot.com")

# Build webhook URL
webhook_url = f"https://{DOMAIN}/{BOT_TOKEN}"
safe_webhook_url = webhook_url.replace(BOT_TOKEN, "[REDACTED]")

print(f"Registering webhook to: {safe_webhook_url}")

# Register webhook
telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
response = requests.get(telegram_url, timeout=10)
response_data = response.json()

if response_data.get('ok'):
    print(f"✓ Webhook registered successfully!")
    print(f"  URL: {safe_webhook_url}")
else:
    print(f"✗ Failed to register webhook:")
    print(f"  {response_data}")

# Check current webhook status
print("\nChecking webhook info...")
info_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"
info_response = requests.get(info_url, timeout=10)
info_data = info_response.json()

if info_data.get('ok'):
    result = info_data['result']
    current_url = result.get('url', 'Not set')
    if BOT_TOKEN in current_url:
        current_url = current_url.replace(BOT_TOKEN, "[REDACTED]")

    print(f"Current webhook URL: {current_url}")
    print(f"Pending updates: {result.get('pending_update_count', 0)}")
    if result.get('last_error_message'):
        print(f"⚠️  Last error: {result.get('last_error_message')}")
        print(f"   Error date: {result.get('last_error_date')}")
