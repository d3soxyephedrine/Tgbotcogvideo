# 📦 Replit → Railway Data Migration Guide

Complete guide to migrating all your user data, credits, purchases, and conversations from Replit to Railway.

---

## 🎯 What Gets Migrated

✅ **Users** - All user accounts, credits, API keys
✅ **Conversations** - All chat histories
✅ **Messages** - Complete conversation data
✅ **Memories** - All AI memories
✅ **Payments** - Purchase records
✅ **Transactions** - Credit transactions
✅ **Crypto Payments** - Crypto purchase history
✅ **Telegram Payments** - Star payment records

---

## 🚀 Migration Methods

Choose one of these methods:

### Method 1: Python Script (Recommended for Large Databases)

**Best for:** 500+ users, detailed logging, error handling

```bash
# Install dependencies
pip install sqlalchemy psycopg2-binary

# Run migration script
python migrate_replit_to_railway.py
```

**What it does:**
- ✅ Tests both database connections
- ✅ Shows you exactly what will be migrated
- ✅ Migrates tables in correct order (respects foreign keys)
- ✅ Skips duplicates automatically
- ✅ Verifies migration succeeded
- ✅ Provides detailed logs

**Prompts you'll see:**
```
📥 Enter your REPLIT database URL:
   > postgresql://user:pass@ep-xxx.us-east-2.aws.neon.tech/db

📤 Enter your RAILWAY database URL:
   > postgresql://postgres:pass@containers-us-west-99.railway.app/railway

Continue with migration? (yes/no):
```

---

### Method 2: Shell Script (Faster, Simpler)

**Best for:** Quick migrations, < 500 users

```bash
# Make executable
chmod +x migrate_db_quick.sh

# Run migration
./migrate_db_quick.sh
```

**What it does:**
- ✅ Uses `pg_dump` and `pg_restore` (industry standard)
- ✅ Faster for large datasets
- ✅ Handles duplicates automatically
- ✅ Shows before/after counts

**Requirements:**
- `postgresql-client` tools installed
- Access to both databases

---

## 📋 Step-by-Step Process

### Step 1: Get Your Database URLs

#### **Replit Database URL:**
1. Go to your Replit project
2. Click **Tools → Secrets**
3. Copy the `DATABASE_URL` value
4. Should look like: `postgresql://neondb_owner:...@ep-xxx.us-east-2.aws.neon.tech/neondb`

#### **Railway Database URL:**
1. Go to Railway dashboard
2. Click your **PostgreSQL** service
3. Go to **Variables** tab
4. Copy the `DATABASE_URL` value
5. Should look like: `postgresql://postgres:...@containers-us-west-XX.railway.app/railway`

---

### Step 2: Choose Migration Method

**Use Python Script if:**
- ✅ You want detailed logs
- ✅ You have a large database (500+ users)
- ✅ You want to see exactly what's migrated
- ✅ You want error handling and retry logic

**Use Shell Script if:**
- ✅ You want the fastest migration
- ✅ You have PostgreSQL tools installed
- ✅ You prefer command-line tools
- ✅ You have a smaller database (< 500 users)

---

### Step 3: Run Migration

#### **Option A: Python Script**

```bash
python migrate_replit_to_railway.py
```

**Sample output:**
```
🚀 Replit → Railway Database Migration
========================================

📥 Enter your REPLIT database URL:
   > postgresql://...

📤 Enter your RAILWAY database URL:
   > postgresql://...

✓ Replit DB connected - Found 127 users
✓ Railway DB connected

📊 Migration Plan
========================================
📥 SOURCE (Replit):
   user                    127 rows
   conversation            453 rows
   message                3821 rows
   memory                  89 rows
   ...

Continue with migration? (yes/no): yes

🔄 Starting Migration
========================================
📦 Users (accounts, credits, API keys)
  ✓ user: Migrated 127 rows, skipped 0
📦 Conversations
  ✓ conversation: Migrated 453 rows, skipped 0
...

✅ Migration Complete - Verification
========================================
✓ user                 Source:   127  →  Dest:   127
✓ conversation         Source:   453  →  Dest:   453
✓ message              Source:  3821  →  Dest:  3821
...

🎉 SUCCESS! All data migrated successfully!
```

#### **Option B: Shell Script**

```bash
./migrate_db_quick.sh
```

**Sample output:**
```
🚀 Quick Database Migration: Replit → Railway
==============================================

📥 Step 1: Enter your REPLIT database URL
   > postgresql://...

📤 Step 2: Enter your RAILWAY database URL
   > postgresql://...

🔍 Step 3: Testing connections...
✓ Replit DB connected - Found 127 users
✓ Railway DB connected

Continue? (yes/no): yes

📦 Step 4: Dumping Replit database...
✓ Dump completed: 2.4M

📤 Step 5: Restoring to Railway database...
✓ Restore completed

🔍 Step 6: Verifying migration...

✅ Migration Results:
==============================================
   Users:         127
   Conversations: 453
   Messages:      3821
   Memories:      89
==============================================

🎉 Migration complete!
```

---

### Step 4: Update Railway Environment

1. Go to your Railway **main service** (Flask app)
2. Click **Variables** tab
3. Verify `DATABASE_URL` is set to the Railway PostgreSQL URL
4. If not, update it to match the PostgreSQL service's DATABASE_URL
5. Click **Restart**

---

### Step 5: Verify Migration

#### **Check 1: Diagnostic Page**
Visit: `https://your-railway-app.railway.app/diagnostic`

Should show:
```
✅ Database Configured: YES
✅ Database Available: YES
✅ Stats:
   - users: 127
   - conversations: 453
   - messages: 3821
```

#### **Check 2: User Login**
1. Try logging in via Telegram bot
2. Send `/balance` - should show correct credits
3. Send a message - should work
4. Check web chat - should show old conversations

#### **Check 3: Credits & Purchases**
1. Check that user credits are preserved
2. Verify purchase history is intact
3. Test buying new credits

---

## ⚠️ Important Notes

### About Duplicates
- Both migration methods **skip duplicates** automatically
- Based on primary keys (IDs)
- Safe to run multiple times
- Won't double-credit users

### About Data Integrity
- **Foreign keys are respected** - parent tables migrated first
- **No data loss** - all relationships preserved
- **Transactions** - each table migrated atomically

### About Timing
- **Small DB** (< 100 users): ~30 seconds
- **Medium DB** (100-500 users): ~2-5 minutes
- **Large DB** (500+ users): ~5-15 minutes

---

## 🔧 Troubleshooting

### Connection Failed

**Error:** `Failed to connect to database`

**Solutions:**
1. Check database URL is correct
2. Ensure database is running (Railway/Replit)
3. Check IP whitelist settings
4. Verify SSL mode: add `?sslmode=require` to URL

### Duplicate Key Errors

**Error:** `ERROR: duplicate key value violates unique constraint`

**This is NORMAL** if:
- You're re-running the migration
- Railway DB already has some data
- The script continues and skips duplicates

**Not normal** if:
- Every single row is a duplicate
- Check you're migrating to the right database

### Missing Tables

**Error:** `relation "user" does not exist`

**Solutions:**
1. Run your Flask app once on Railway first
2. This creates all tables
3. Then run migration script

### Timeout Errors

**Error:** `Connection timeout`

**Solutions:**
1. Add `connect_timeout=30` to database URL
2. Example: `postgresql://user:pass@host/db?connect_timeout=30`
3. Try during off-peak hours
4. Use Railway's database (same region as app)

---

## 🎯 Post-Migration Checklist

After migration, verify:

- [ ] Users can log in via Telegram
- [ ] `/balance` shows correct credits
- [ ] Old conversations visible in web chat
- [ ] Memories are preserved
- [ ] Purchase history intact
- [ ] New messages work
- [ ] Credit purchases work
- [ ] `/diagnostic` shows all tables populated

---

## 🔄 Rollback Plan

If something goes wrong:

### Keep Replit Running
- Don't delete your Replit database yet
- Keep it as backup for 1-2 weeks
- Test Railway thoroughly first

### Switch Back to Replit
1. In Railway, go to **Variables**
2. Change `DATABASE_URL` back to Replit URL
3. Restart service
4. Everything works as before

### Re-run Migration
- Both scripts are safe to re-run
- Duplicates are skipped
- Only new data is added

---

## 📊 Performance Comparison

| Database | Location | Auto-suspend | Backups | Speed |
|----------|----------|--------------|---------|-------|
| **Replit Neon** | US East | Yes (free tier) | Auto | Medium |
| **Railway** | US West | No | Manual | Fast |

**Recommendation:** Use Railway for production (no auto-suspend).

---

## ✅ Success Indicators

You'll know migration succeeded when:

1. **Logs show:** "Migration complete!"
2. **Diagnostic page:** Shows correct row counts
3. **Users:** Can log in and see their credits
4. **Conversations:** Old chats appear in web interface
5. **No errors:** In Railway deployment logs

---

## 🆘 Need Help?

If migration fails:

1. **Check logs** from migration script
2. **Verify database URLs** are correct
3. **Test connections** manually:
   ```bash
   psql "your-database-url" -c "SELECT COUNT(*) FROM user;"
   ```
4. **Run diagnostic** on both databases
5. **Keep Replit DB** as backup

---

## 🎉 After Successful Migration

1. **Test everything** for 24-48 hours
2. **Monitor Railway logs** for errors
3. **Keep Replit DB** as backup for 1-2 weeks
4. **Update documentation** with new DATABASE_URL
5. **Celebrate!** 🎊 Your data is now on Railway!
