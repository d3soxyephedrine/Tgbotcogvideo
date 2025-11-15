# Webhook Setup (One-Time)

Only run this when you deploy to a new domain or change your webhook URL.

## Option 1: Use the script (recommended)

```bash
python3 set_webhook.py
```

The script automatically reads `BOT_TOKEN` and `RAILWAY_PUBLIC_DOMAIN` from environment.

## Option 2: Manual setup

```bash
export BOT_TOKEN="your_bot_token_here"
export DOMAIN="your-app.up.railway.app"

curl -X POST "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"https://${DOMAIN}/${BOT_TOKEN}\"}"
```

## When to run

- Initial Railway deployment
- After changing domains
- After updating webhook configuration

**You do NOT need to run this on every server restart.**
