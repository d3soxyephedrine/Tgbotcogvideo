# Railway Deployment Setup

## Required Environment Variables

Set these in Railway dashboard under **Variables**:

### 1. RAILWAY_PUBLIC_DOMAIN
**Required for webhook to work**

Set this to your Railway-assigned domain:
```
RAILWAY_PUBLIC_DOMAIN=cke-production.up.railway.app
```

Or if you have a custom domain:
```
RAILWAY_PUBLIC_DOMAIN=ko2bot.com
```

**⚠️ Without this, the webhook will fail and Telegram messages won't reach your bot.**

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
