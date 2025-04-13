import os
import logging
import threading
import time
import requests
from flask import Flask, request, jsonify
from telegram_handler import process_update, send_message
from llm_api import generate_response
from models import db, User, Message

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Flask application
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default_secret_key")

# Configure the database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize the database
db.init_app(app)

# Create all tables
with app.app_context():
    db.create_all()
    logger.info("Database tables created")

# Get environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable is not set!")

# Replit URL (for keepalive pings)
# We'll just use localhost since we're pinging ourselves
KEEPALIVE_URL = "http://localhost:5000"

@app.route('/')
def home():
    """Health check endpoint that returns a simple message"""
    return "I'm alive"

@app.route('/stats')
def stats():
    """Endpoint to view basic statistics about the bot usage"""
    try:
        user_count = User.query.count()
        message_count = Message.query.count()
        recent_messages = Message.query.order_by(Message.created_at.desc()).limit(5).all()
        
        # Format recent messages for display
        recent_msgs_formatted = []
        for msg in recent_messages:
            user = User.query.get(msg.user_id)
            username = user.username or user.first_name or f"User {user.telegram_id}"
            recent_msgs_formatted.append({
                "id": msg.id,
                "user": username,
                "message": msg.user_message[:30] + "..." if len(msg.user_message) > 30 else msg.user_message,
                "time": msg.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "model": msg.model_used
            })
        
        return jsonify({
            "stats": {
                "total_users": user_count,
                "total_messages": message_count
            },
            "recent_messages": recent_msgs_formatted
        })
    except Exception as e:
        logger.error(f"Error generating stats: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Keepalive function
def keep_alive():
    """Function to ping the app every 4 minutes to prevent Replit from sleeping"""
    while True:
        try:
            logger.info("Pinging server to keep it alive...")
            requests.get(KEEPALIVE_URL)
            logger.info("Ping successful")
        except Exception as e:
            logger.error(f"Error pinging server: {str(e)}")
        # Sleep for 4 minutes (240 seconds)
        time.sleep(240)

# Start keepalive thread
keepalive_thread = threading.Thread(target=keep_alive, daemon=True)
keepalive_thread.start()
logger.info("Started keepalive thread")

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    """Webhook endpoint to receive updates from Telegram"""
    if not BOT_TOKEN:
        return jsonify({"error": "Bot token not configured"}), 500
        
    try:
        # Parse update from Telegram
        update = request.get_json()
        logger.debug(f"Received update: {update}")
        
        # Process the update
        process_update(update)
        
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Helper endpoint to set the webhook URL for Telegram"""
    if not BOT_TOKEN:
        return jsonify({"error": "Bot token not configured"}), 500
        
    try:
        url = request.args.get('url')
        if not url:
            return jsonify({"error": "URL parameter is required"}), 400
            
        webhook_url = f"{url}/{BOT_TOKEN}"
        telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
        
        # For demonstration - in production should use requests
        return jsonify({
            "info": "Please make this request to set your webhook:", 
            "url": telegram_url
        })
    except Exception as e:
        logger.error(f"Error setting webhook: {str(e)}")
        return jsonify({"error": str(e)}), 500
        
@app.route('/test', methods=['POST'])
def test_bot():
    """Test endpoint to simulate a message to the bot without Telegram"""
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({"error": "Request must include 'message' field"}), 400
            
        user_message = data['message']
        
        # Create a mock Telegram update
        mock_update = {
            "update_id": 123456789,
            "message": {
                "message_id": 100,
                "from": {
                    "id": 1234567890,  # Fake Telegram ID
                    "is_bot": False,
                    "first_name": "Test",
                    "username": "testuser"
                },
                "chat": {
                    "id": 1234567890,  # Same as from.id
                    "first_name": "Test",
                    "username": "testuser",
                    "type": "private"
                },
                "date": int(time.time()),
                "text": user_message
            }
        }
        
        # Process the update just like a real Telegram update
        response = generate_response(user_message)
        process_update(mock_update)
        
        return jsonify({
            "status": "success",
            "user_message": user_message,
            "bot_response": response
        })
    except Exception as e:
        logger.error(f"Error in test endpoint: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Run the Flask application
    # Note: keepalive thread is already started in global scope
    app.run(host='0.0.0.0', port=5000, debug=True)
