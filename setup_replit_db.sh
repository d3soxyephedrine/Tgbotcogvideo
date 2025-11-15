#!/bin/bash
# Replit Database Setup Helper Script

echo "🔧 Replit PostgreSQL Setup Verification"
echo "========================================="
echo ""

# Check if PostgreSQL module is in .replit
echo "📋 Checking .replit configuration..."
if grep -q "postgresql-16" .replit; then
    echo "✅ PostgreSQL module found in .replit"
else
    echo "❌ PostgreSQL module NOT found in .replit"
    echo "   Add 'postgresql-16' to modules array"
    exit 1
fi

echo ""
echo "🔍 Checking environment variables..."

# Check DATABASE_URL
if [ -z "$DATABASE_URL" ]; then
    echo "⚠️  DATABASE_URL is not set"
    echo "   Action needed:"
    echo "   1. Go to Tools → Secrets in Replit"
    echo "   2. Click '+ New Secret'"
    echo "   3. Add DATABASE_URL (Replit should auto-suggest it)"
    echo "   4. Restart your Repl"
else
    echo "✅ DATABASE_URL is configured"
    echo "   Starts with: ${DATABASE_URL:0:30}..."
fi

# Check BOT_TOKEN
if [ -z "$BOT_TOKEN" ]; then
    echo "❌ BOT_TOKEN is not set"
    echo "   Get your token from @BotFather on Telegram"
else
    echo "✅ BOT_TOKEN is configured"
fi

# Check OPENROUTER_API_KEY
if [ -z "$OPENROUTER_API_KEY" ]; then
    echo "⚠️  OPENROUTER_API_KEY is not set"
    echo "   AI features will be limited"
else
    echo "✅ OPENROUTER_API_KEY is configured"
fi

echo ""
echo "🎯 Replit-specific variables:"

# Check REPLIT_DOMAINS
if [ -z "$REPLIT_DOMAINS" ]; then
    echo "⚠️  REPLIT_DOMAINS not detected"
    echo "   This is auto-set by Replit, should appear when you run the app"
else
    echo "✅ REPLIT_DOMAINS: $REPLIT_DOMAINS"
fi

echo ""
echo "📊 Database connection test..."

# Try to connect to PostgreSQL (if psql is available)
if command -v psql &> /dev/null && [ ! -z "$DATABASE_URL" ]; then
    echo "Testing connection..."
    if psql "$DATABASE_URL" -c "SELECT 1;" &> /dev/null; then
        echo "✅ Database connection successful!"
    else
        echo "❌ Database connection failed"
        echo "   The database might not be ready yet"
        echo "   Try running your app first"
    fi
else
    echo "⏭️  Skipping connection test (will test on app startup)"
fi

echo ""
echo "🚀 Next steps:"
echo "1. Make sure all required secrets are set in Tools → Secrets"
echo "2. Click the Run button to start your app"
echo "3. Check logs for 'Database connection validated successfully'"
echo "4. Visit /diagnostic endpoint to verify setup"
echo ""
echo "📖 For detailed setup instructions, see REPLIT_SETUP.md"
