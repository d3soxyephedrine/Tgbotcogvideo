# Automatic Webhook Setup on Railway

## Problem
Telegram webhooks get deleted/reset after Railway deployments, causing the bot to stop responding.

## Solution
Automatic webhook setup on every deployment via startup script.

## How It Works

### Files Created
1. **`set_webhook.py`** - Python script that sets the Telegram webhook
2. **`railway_start.sh`** - Startup script that runs webhook setup then starts server
3. **`Procfile`** - Updated to use the startup script

### Deployment Flow
```
Railway Deployment
    ↓
railway_start.sh executes
    ↓
set_webhook.py runs (sets webhook)
    ↓
Gunicorn starts (web server)
    ↓
Bot is live and responsive
```

### Webhook URL
```
https://tgbotcogvideo-production.up.railway.app/8129731076:AAE_RjwUf0_6k5PKwAtOYfgWvLIocWejQcY
```

## Features

✅ **Automatic** - Runs on every deployment
✅ **Retry Logic** - 3 attempts with exponential backoff
✅ **Non-blocking** - Server starts even if webhook fails
✅ **Environment Variables** - Uses `BOT_TOKEN` and `RAILWAY_PUBLIC_DOMAIN`
✅ **Logging** - Clear output in Railway logs

## Verify It Works

After deployment, check Railway logs for:
```
🚀 Railway Startup Script
==========================
📡 Setting Telegram webhook...
🔗 Setting webhook to: https://tgbotcogvideo-production.up.railway.app/...
✅ Webhook set successfully!
   URL: https://...
   Response: Webhook was set
```

## Manual Webhook Check

If you ever need to manually verify the webhook:
```bash
curl https://api.telegram.org/bot8129731076:AAE_RjwUf0_6k5PKwAtOYfgWvLIocWejQcY/getWebhookInfo
```

## Manual Webhook Set

If you need to manually set it after deployment:

**Quick one-liner:**
```bash
curl -X POST "https://api.telegram.org/bot8129731076:AAE_RjwUf0_6k5PKwAtOYfgWvLIocWejQcY/setWebhook" -H "Content-Type: application/json" -d '{"url":"https://tgbotcogvideo-production.up.railway.app/8129731076:AAE_RjwUf0_6k5PKwAtOYfgWvLIocWejQcY"}'
```

**Alternative (GET request):**
```bash
curl "https://api.telegram.org/bot8129731076:AAE_RjwUf0_6k5PKwAtOYfgWvLIocWejQcY/setWebhook?url=https://tgbotcogvideo-production.up.railway.app/8129731076:AAE_RjwUf0_6k5PKwAtOYfgWvLIocWejQcY"
```

**Or use the web endpoint:**
```bash
curl "https://tgbotcogvideo-production.up.railway.app/set_webhook"
```

## Troubleshooting

**Bot not responding after deployment:**
1. Check Railway logs for webhook setup messages
2. Verify webhook with `getWebhookInfo` (command above)
3. Check if `BOT_TOKEN` environment variable is set in Railway
4. Manually trigger webhook setup via `/set_webhook` endpoint

**Webhook setup failing:**
- Check Railway logs for error messages
- Verify Railway domain hasn't changed
- Check internet connectivity from Railway (rare issue)

## Environment Variables Required

- `BOT_TOKEN` - Your Telegram bot token (required)
- `RAILWAY_PUBLIC_DOMAIN` - Auto-set by Railway (optional, has fallback)

---

**No more manual webhook setup needed!** 🎉
