#!/bin/bash
# Railway startup script - sets webhook then starts web server

echo "🚀 Railway Startup Script"
echo "=========================="

# Set webhook
echo "📡 Setting Telegram webhook..."
python3 set_webhook.py

# Check if webhook setup succeeded
if [ $? -eq 0 ]; then
    echo "✅ Webhook configured successfully"
else
    echo "⚠️  Webhook setup failed, but continuing with server startup..."
fi

echo ""
echo "🌐 Starting Gunicorn web server..."
echo "=========================="

# Start the main application
exec gunicorn --config gunicorn.conf.py main:app
