# 🚀 Replit Database Setup Guide

## ✅ Quick Setup (3 Steps)

### Step 1: PostgreSQL is Already Configured!

Your `.replit` file already has PostgreSQL:
```toml
modules = ["python-3.11", "postgresql-16"]
```

This means Replit will automatically:
- ✅ Provision a PostgreSQL database
- ✅ Set the `DATABASE_URL` environment variable
- ✅ Keep the database running

### Step 2: Check Your DATABASE_URL

1. In your Replit, click on **Tools** → **Secrets**
2. Look for `DATABASE_URL`
3. It should look like:
   ```
   postgresql://neondb_owner:PASSWORD@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

If you don't see it:
1. Go to **Tools** → **Secrets**
2. Click **+ New Secret**
3. Replit should auto-suggest `DATABASE_URL` from the PostgreSQL module
4. Click **Add**

### Step 3: Run Your App

Just click **Run** and Replit will:
1. Start PostgreSQL
2. Connect your app to the database
3. Create all tables automatically
4. Register your webhook

---

## 🔍 Verify It's Working

### Check 1: Logs
Look for these lines in the console:
```
✓ DATABASE_URL is configured
✓ Database initialization attempt 1/3
✓ Database connection validated successfully
✓ Database tables created successfully
```

### Check 2: Diagnostic Page
Visit: `https://your-repl-name.your-username.repl.co/diagnostic`

You should see:
- **Database Configured:** ✅ YES
- **Database Available:** ✅ YES

### Check 3: Health Endpoint
Visit: `https://your-repl-name.your-username.repl.co/health`

Response should show:
```json
{
  "database": {
    "configured": true,
    "available": true,
    "status": "responsive"
  }
}
```

---

## 🎛️ Environment Variables Needed

Make sure these are in **Tools → Secrets**:

### Required:
- `BOT_TOKEN` - Your Telegram bot token
- `DATABASE_URL` - Auto-provided by PostgreSQL module
- `OPENROUTER_API_KEY` - For AI responses

### Optional:
- `NOWPAYMENTS_API_KEY` - For crypto payments
- `NOWPAYMENTS_IPN_SECRET` - For payment verification
- `SESSION_SECRET` - Flask session secret (auto-generated if missing)

---

## 🔧 Troubleshooting

### "Database not connected"

1. **Check PostgreSQL module is active:**
   - Open `.replit` file
   - Confirm: `modules = ["python-3.11", "postgresql-16"]`

2. **Check DATABASE_URL exists:**
   - Tools → Secrets → Look for `DATABASE_URL`
   - If missing, add it manually

3. **Restart the Repl:**
   - Stop the app
   - Click **Run** again

### "Invalid DATABASE_URL"

If you see connection errors:
1. The DATABASE_URL might be from an old Neon instance
2. Delete the `DATABASE_URL` secret
3. Replit will auto-generate a new one
4. Restart

### "Database endpoint disabled" (Neon)

This happens with Neon free tier. Options:
1. **Use Replit's internal PostgreSQL** (recommended)
   - Faster
   - More reliable
   - Auto-managed

2. **Or re-enable Neon:**
   - Go to https://console.neon.tech
   - Find your project
   - Click "Resume"

---

## 🆚 Replit vs Railway PostgreSQL

| Feature | Replit | Railway |
|---------|--------|---------|
| Setup | Automatic | Manual |
| Auto-suspend | No (always on) | No (always on) |
| Backups | Auto-managed | Manual |
| Migration | Not needed | Manual |
| Speed | Fast (same region) | Fast |
| Free tier | Limited storage | 512 MB |

**Recommendation:** Use Replit's built-in PostgreSQL for simplicity!

---

## 🎯 What's Already Done

Your code is **already configured** for Replit:
- ✅ Webhook uses `REPLIT_DOMAINS` automatically
- ✅ Database initialization with retry logic
- ✅ Auto-creates all tables on first run
- ✅ Health and diagnostic endpoints work

Just click **Run** and you're good to go! 🚀
