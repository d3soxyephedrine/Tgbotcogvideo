#!/bin/bash
# Railway startup script - sets webhook then starts web server

echo "🚀 Railway Startup Script"
echo "=========================="

# Get environment variables
BOT_TOKEN="${BOT_TOKEN}"

# Prefer explicit webhook domain if provided, then Railway-provided domains
if [ -n "${TELEGRAM_WEBHOOK_DOMAIN}" ]; then
    DOMAIN="${TELEGRAM_WEBHOOK_DOMAIN}"
elif [ -n "${RAILWAY_PUBLIC_DOMAIN}" ]; then
    DOMAIN="${RAILWAY_PUBLIC_DOMAIN}"
elif [ -n "${RAILWAY_STATIC_URL}" ]; then
    DOMAIN="${RAILWAY_STATIC_URL}"
else
    DOMAIN="tgbotcogvideo-production.up.railway.app"
fi

# Strip protocol if DOMAIN already includes it
DOMAIN="${DOMAIN#https://}"
DOMAIN="${DOMAIN#http://}"

if [ -z "$BOT_TOKEN" ]; then
    echo "⚠️  BOT_TOKEN not set, skipping webhook setup"
else
    # Construct webhook URL
    WEBHOOK_URL="https://${DOMAIN}/${BOT_TOKEN}"
    TELEGRAM_API="https://api.telegram.org/bot${BOT_TOKEN}/setWebhook"

    echo "📡 Setting Telegram webhook..."
    echo "🔗 Webhook URL: ${WEBHOOK_URL}"

    # Set webhook using curl (always available on Railway)
    RESPONSE=$(curl -s -X POST "${TELEGRAM_API}" \
        -H "Content-Type: application/json" \
        -d "{\"url\":\"${WEBHOOK_URL}\"}" \
        --max-time 10)

    # Check if successful
    if echo "$RESPONSE" | grep -q '"ok":true'; then
        echo "✅ Webhook set successfully!"
        echo "   Response: $RESPONSE"
    else
        echo "❌ Webhook setup failed"
        echo "   Response: $RESPONSE"
        echo "⚠️  Continuing with server startup anyway..."
    fi
fi

echo ""
echo "🌐 Starting Gunicorn web server..."
echo "=========================="

# Start the main application
exec gunicorn --config gunicorn.conf.py main:app
