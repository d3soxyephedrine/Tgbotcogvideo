#!/bin/bash
# Railway startup script - sets webhook then starts web server

echo "🚀 Railway Startup Script"
echo "=========================="

# Get environment variables
BOT_TOKEN="${BOT_TOKEN}"
DOMAIN="${RAILWAY_PUBLIC_DOMAIN:-tgbotcogvideo-production.up.railway.app}"

echo "📋 Startup Configuration:"
echo "   RAILWAY_PUBLIC_DOMAIN: ${RAILWAY_PUBLIC_DOMAIN:-NOT SET (using default)}"
echo "   Domain being used: ${DOMAIN}"
echo "   BOT_TOKEN: ${BOT_TOKEN:0:10}..."

if [ -z "$BOT_TOKEN" ]; then
    echo "⚠️  BOT_TOKEN not set, skipping webhook setup"
else
    # Construct webhook URL
    WEBHOOK_URL="https://${DOMAIN}/${BOT_TOKEN}"
    TELEGRAM_API="https://api.telegram.org/bot${BOT_TOKEN}/setWebhook"

    echo ""
    echo "📡 Setting Telegram webhook..."
    echo "🔗 Domain: ${DOMAIN}"
    echo "🔗 Full webhook URL: https://[DOMAIN]/[TOKEN]"

    # Set webhook using curl (always available on Railway)
    # Using POST with JSON body as per Telegram API best practices
    RESPONSE=$(curl -s -X POST "${TELEGRAM_API}" \
        -H "Content-Type: application/json" \
        -d "{\"url\":\"${WEBHOOK_URL}\"}" \
        --max-time 10)

    # Check if successful
    if echo "$RESPONSE" | grep -q '"ok":true'; then
        echo "✅ Webhook set successfully!"

        # Extract webhook info from response
        WEBHOOK_INFO=$(echo "$RESPONSE" | grep -o '"url":"[^"]*"' || echo "N/A")
        echo "   Webhook info: $WEBHOOK_INFO"
    else
        echo "❌ Webhook setup failed"
        echo "   Response: $RESPONSE"
        echo "⚠️  Continuing with server startup anyway..."
        echo "   Note: Gunicorn will attempt to set webhook again on startup"
    fi
fi

echo ""
echo "🌐 Starting Gunicorn web server..."
echo "=========================="

# Start the main application
# Webhook will be set again in gunicorn.conf.py's when_ready() hook as a safety measure
exec gunicorn --config gunicorn.conf.py main:app
