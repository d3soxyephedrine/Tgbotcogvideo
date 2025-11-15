# Railway Deployment Setup

## ⚠️ CRITICAL: Required Environment Variables

Set these in Railway dashboard under **Variables** tab:

### 1. RAILWAY_PUBLIC_DOMAIN (REQUIRED)
**Without this variable, the bot will NOT receive Telegram messages!**

Go to Railway dashboard → Your service → **Variables** → **New Variable**

**Variable name:** `RAILWAY_PUBLIC_DOMAIN`

**Variable value:** Your Railway domain (one of these):
- Railway auto domain: `cke-production.up.railway.app`
- Custom domain: `ko2bot.com` (if you configured one)

**How to find your domain:**
- Railway dashboard shows it under **Settings** → **Domains**
- Or in **Deployments** logs, look for the public URL

```
RAILWAY_PUBLIC_DOMAIN=cke-production.up.railway.app
```

**⚠️ The app will start but webhook will NOT be registered without this variable.**

### 2. BOT_TOKEN
Your Telegram bot token from @BotFather:
```
BOT_TOKEN=8129731076:AAE_RjwUf0_6k5PKwAtOYfgWvLIocWejQcY
```

### 3. DATABASE_URL
PostgreSQL connection string (Railway sets this automatically when you add a Postgres database)

### 4. Optional Variables
- `OPENROUTER_API_KEY` - For AI features
- `NOWPAYMENTS_API_KEY` - For crypto payments
- `NOWPAYMENTS_IPN_SECRET` - For payment verification

## Deployment Steps

1. **Connect Repository** to Railway
2. **Add PostgreSQL** database (optional but recommended)
3. **Set Environment Variables** (especially `RAILWAY_PUBLIC_DOMAIN` and `BOT_TOKEN`)
4. **Deploy** - Railway will auto-deploy
5. **Verify** webhook is set correctly by checking logs for:
   ```
   ✓ Webhook registered successfully
   ```

## Checking Your Domain

Your Railway domain is shown in the project dashboard. It looks like:
- `your-app-name-production.up.railway.app`
- Or your custom domain if configured

Use this exact value for `RAILWAY_PUBLIC_DOMAIN`.

## Webhook Setup

The app automatically registers the webhook on startup using:
```
https://{RAILWAY_PUBLIC_DOMAIN}/{BOT_TOKEN}
```

No manual webhook setup needed if environment variables are correct.
