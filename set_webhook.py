#!/usr/bin/env python3
"""
Auto-set Telegram webhook after Railway deployment
Runs automatically via Procfile release phase
"""
import os
import sys
import requests
import time

def set_telegram_webhook():
    """Set Telegram webhook using environment variables"""

    # Get bot token from environment
    bot_token = os.environ.get('BOT_TOKEN')
    if not bot_token:
        print("❌ BOT_TOKEN not found in environment")
        sys.exit(1)

    # Get domain from Railway environment
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
    if not domain:
        # Fallback to Railway's static URL
        domain = os.environ.get('RAILWAY_STATIC_URL', 'tgbotcogvideo-production.up.railway.app')

    # Construct webhook URL
    webhook_url = f"https://{domain}/{bot_token}"
    telegram_api_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"

    print(f"🔗 Setting webhook to: {webhook_url}")

    # Retry logic for network issues
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                telegram_api_url,
                json={'url': webhook_url},
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    print(f"✅ Webhook set successfully!")
                    print(f"   URL: {webhook_url}")
                    print(f"   Response: {result.get('description', 'Success')}")
                    sys.exit(0)
                else:
                    print(f"❌ Telegram API returned error: {result}")
                    sys.exit(1)
            else:
                print(f"❌ HTTP {response.status_code}: {response.text}")
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    print(f"   Retrying in {wait_time}s... ({attempt}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    sys.exit(1)

        except requests.exceptions.RequestException as e:
            print(f"❌ Network error: {e}")
            if attempt < max_retries:
                wait_time = 2 ** attempt
                print(f"   Retrying in {wait_time}s... ({attempt}/{max_retries})")
                time.sleep(wait_time)
            else:
                print("❌ Failed after all retries")
                sys.exit(1)

if __name__ == '__main__':
    print("🚀 Railway Post-Deployment: Setting Telegram Webhook")
    print("=" * 60)
    set_telegram_webhook()
