# Railway Migration Guide

This guide provides step-by-step instructions for migrating the Telegram Bot from Replit to Railway.

## Overview

This application is a Flask-based Telegram bot using:
- **Python 3.11**
- **PostgreSQL 16** (recommended)
- **Gunicorn** WSGI server (3 workers, 300s timeout)
- **Flask-SQLAlchemy** for database ORM
- **python-telegram-bot** for Telegram API

## Pre-Migration Checklist

### 1. Runtime Environment
- ✅ Python 3.11 specified in `.python-version`
- ✅ Dependencies listed in `pyproject.toml`
- ✅ Procfile created for Railway deployment
- ✅ Gunicorn configuration updated to use `PORT` env var

### 2. Replit-Specific Code Removed
The following Replit-specific code has been identified and needs to be removed:
- ❌ Keepalive thread (lines 950-966 in main.py)
- ❌ KEEPALIVE_URL and KEEPALIVE_PORT configuration (lines 178-181)
- ❌ REPLIT_DOMAINS/REPLIT_DEV_DOMAIN references (lines 1074, 1572, 1948)

### 3. Database Configuration
- Uses PostgreSQL with connection pooling
- Current config: 10 pool size, 20 max overflow, 300s pool recycle
- Requires `DATABASE_URL` environment variable

## Required Environment Variables

### Critical (Required for Core Functionality)
```bash
BOT_TOKEN=your_telegram_bot_token_here
DATABASE_URL=postgresql://user:password@host:port/database
```

### Optional (For Extended Features)
```bash
# AI/LLM Integration
OPENROUTER_API_KEY=your_openrouter_api_key
MODEL=deepseek/deepseek-chat-v3-0324

# Video/Image Generation
NOVITA_API_KEY=your_novita_api_key

# Payment Processing
NOWPAYMENTS_API_KEY=your_nowpayments_api_key
NOWPAYMENTS_IPN_SECRET=your_nowpayments_ipn_secret

# Security & Admin
SESSION_SECRET=your_random_session_secret
ADMIN_EXPORT_TOKEN=your_admin_export_token

# Server Configuration (Railway provides automatically)
PORT=5000  # Railway sets this automatically
```

## Railway Deployment Steps

### Step 1: Create Railway Project
1. Go to [Railway.app](https://railway.app)
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Connect your GitHub repository

### Step 2: Provision PostgreSQL Database
1. In your Railway project, click "+ New"
2. Select "Database" → "PostgreSQL"
3. Railway will automatically provision a PostgreSQL 16 instance
4. The `DATABASE_URL` environment variable will be automatically set

### Step 3: Configure Environment Variables
In Railway project settings → Variables, add:

```bash
# Required
BOT_TOKEN=<your_telegram_bot_token>

# Optional (add as needed)
OPENROUTER_API_KEY=<your_key>
NOVITA_API_KEY=<your_key>
NOWPAYMENTS_API_KEY=<your_key>
NOWPAYMENTS_IPN_SECRET=<your_secret>
SESSION_SECRET=<random_string>
ADMIN_EXPORT_TOKEN=<random_string>
MODEL=deepseek/deepseek-chat-v3-0324
```

**Note:** `DATABASE_URL` and `PORT` are automatically provided by Railway.

### Step 4: Update Webhook URL
Once deployed, Railway will provide a URL like `https://your-app.railway.app`

The bot automatically registers webhooks to `ko2bot.com` (hardcoded in main.py:900).

**Action Required:** Update the webhook registration in `main.py`:
```python
# Change line 900 from:
domain = "ko2bot.com"

# To your Railway domain:
domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "ko2bot.com")
```

Then set in Railway:
```bash
RAILWAY_PUBLIC_DOMAIN=your-app.railway.app
```

Or configure your custom domain (ko2bot.com) to point to Railway.

### Step 5: Database Migration
If you have existing data in Replit:

#### Option A: Manual Export/Import (SQLite → PostgreSQL)
```bash
# On Replit (if using SQLite):
sqlite3 database.db .dump > dump.sql

# On your local machine:
# Convert SQLite dump to PostgreSQL format (manual edits needed)
# Then import to Railway PostgreSQL:
psql $DATABASE_URL < converted_dump.sql
```

#### Option B: pg_dump/pg_restore (PostgreSQL → PostgreSQL)
```bash
# Export from Replit PostgreSQL:
pg_dump <replit_database_url> > backup.sql

# Import to Railway PostgreSQL:
psql <railway_database_url> < backup.sql
```

#### Option C: Fresh Start (Recommended for Testing)
The app will automatically create tables on first run via `db.create_all()` in main.py.

**Note:** For production migrations, consider using Alembic for schema versioning.

### Step 6: Deploy & Verify
1. Push code to GitHub (Railway auto-deploys)
2. Monitor deployment logs in Railway dashboard
3. Check for successful webhook registration in logs
4. Test bot by sending `/start` command in Telegram

## Post-Migration Verification

### Health Checks
- [ ] App starts without errors
- [ ] Database connection successful
- [ ] Telegram webhook registered
- [ ] Bot responds to `/start` command
- [ ] Payment endpoints functional (if configured)
- [ ] Image/video generation working (if configured)

### Monitoring
- Check Railway logs for errors: `gunicorn --log-level info`
- Monitor database connections in Railway PostgreSQL dashboard
- Set up Railway's monitoring/alerting for uptime

## Troubleshooting

### Issue: Webhook not registering
**Solution:** Check `BOT_TOKEN` is set correctly and update domain in `register_telegram_webhook()`

### Issue: Database connection timeout
**Solution:** Railway PostgreSQL should have stable connections. Check `DATABASE_URL` format:
```
postgresql://user:password@host:port/database
```

### Issue: Worker timeout errors
**Solution:** Gunicorn timeout is set to 300s. For longer operations, consider async workers or task queue.

### Issue: Port binding error
**Solution:** Ensure gunicorn.conf.py uses `PORT` env var (already configured)

## Differences: Replit vs Railway

| Feature | Replit | Railway |
|---------|--------|---------|
| **Port** | Fixed 5000 | Dynamic (via `PORT` env var) |
| **Keepalive** | Required (self-ping) | **Not needed** |
| **Database** | Replit-managed PostgreSQL | Railway PostgreSQL |
| **Deployment** | `.replit` config | Procfile + buildpack |
| **Env Vars** | Replit Secrets | Railway Variables |
| **Domain** | `*.replit.dev` | `*.railway.app` + custom |
| **Auto-sleep** | Yes (requires keepalive) | **No** |

## Code Changes Required

### Remove Keepalive Thread (main.py)
```python
# DELETE lines 178-181 (KEEPALIVE configuration)
# DELETE lines 950-966 (keep_alive function and thread)
```

### Remove REPLIT_DOMAINS References (main.py)
```python
# Replace line 1074, 1572, 1948:
# OLD:
domain = os.environ.get("REPLIT_DOMAINS", "").split(',')[0] if os.environ.get("REPLIT_DOMAINS") else os.environ.get("REPLIT_DEV_DOMAIN")

# NEW:
domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "ko2bot.com")
```

### Update Webhook Registration (main.py)
```python
# Line 900 - update to use Railway domain:
domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "ko2bot.com")
```

## Security Considerations

1. **Never commit secrets** to git (use Railway Variables)
2. **Rotate BOT_TOKEN** if exposed
3. **Use strong SESSION_SECRET** (generate with: `python -c "import secrets; print(secrets.token_hex(32))"`)
4. **Enable Railway's** built-in SSL (automatic)
5. **Restrict database access** to Railway's private network

## Performance Optimization

- **Workers:** Currently 3 workers (good for moderate traffic)
- **Pool Size:** 10 DB connections per worker = 30 total
- **Auto-restart:** Workers restart after 1000 requests (prevents memory leaks)
- **Graceful shutdown:** 120s timeout for finishing requests

For high traffic, increase workers in gunicorn.conf.py:
```python
workers = 5  # Increase as needed
```

## Support & Resources

- [Railway Documentation](https://docs.railway.app)
- [Flask-SQLAlchemy Docs](https://flask-sqlalchemy.palletsprojects.com/)
- [Gunicorn Configuration](https://docs.gunicorn.org/en/stable/configure.html)
- [Telegram Bot API](https://core.telegram.org/bots/api)

## Next Steps

1. ✅ Review this guide
2. ⏳ Remove Replit-specific code
3. ⏳ Test locally with Railway-like environment
4. ⏳ Deploy to Railway staging environment
5. ⏳ Migrate database
6. ⏳ Update DNS (if using custom domain)
7. ⏳ Cut over webhook to Railway
8. ⏳ Monitor for 24-48 hours
9. ⏳ Decommission Replit deployment

---

**Last Updated:** 2025-11-15
**Migration Status:** In Progress
