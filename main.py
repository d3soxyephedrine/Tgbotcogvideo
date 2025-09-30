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

# Global flag to track database availability
DB_AVAILABLE = False
DB_INIT_ATTEMPTS = 0
MAX_DB_INIT_ATTEMPTS = 3

def validate_environment():
    """Validate required environment variables at startup"""
    required_vars = ["BOT_TOKEN"]
    optional_vars = ["DATABASE_URL", "XAI_API_KEY", "API_KEY", "MODEL", "SESSION_SECRET"]
    
    missing_required = [var for var in required_vars if not os.environ.get(var)]
    missing_optional = [var for var in optional_vars if not os.environ.get(var)]
    
    if missing_required:
        logger.error(f"CRITICAL: Missing required environment variables: {', '.join(missing_required)}")
        logger.error("Application may not function correctly without these variables")
    
    if missing_optional:
        logger.warning(f"Optional environment variables not set: {', '.join(missing_optional)}")
        logger.warning("Some features may be disabled")
    
    # Log database configuration status
    if os.environ.get("DATABASE_URL"):
        logger.info("DATABASE_URL is configured")
    else:
        logger.warning("DATABASE_URL not configured - database features will be disabled")
    
    return len(missing_required) == 0

# Validate environment variables
env_valid = validate_environment()

# Initialize Flask application
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default_secret_key")

# Configure the database with Cloud Run compatible settings
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_recycle": 300,
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 30,
        "connect_args": {
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000"
        }
    }
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    logger.info("Database configuration applied")
else:
    logger.warning("Skipping database configuration - DATABASE_URL not set")

def validate_database_connection():
    """Validate database connection without blocking startup"""
    global DB_AVAILABLE, DB_INIT_ATTEMPTS
    
    if not DATABASE_URL:
        logger.warning("Database connection skipped - DATABASE_URL not configured")
        return False
    
    try:
        with app.app_context():
            # Test connection
            db.engine.connect()
            logger.info("Database connection validated successfully")
            return True
    except Exception as e:
        logger.error(f"Database connection validation failed: {str(e)}")
        return False

def init_database():
    """Initialize database tables safely with retry logic"""
    global DB_AVAILABLE, DB_INIT_ATTEMPTS
    
    if not DATABASE_URL:
        logger.info("Database initialization skipped - no DATABASE_URL configured")
        return
    
    max_retries = MAX_DB_INIT_ATTEMPTS
    retry_delay = 2
    
    for attempt in range(1, max_retries + 1):
        DB_INIT_ATTEMPTS = attempt
        try:
            logger.info(f"Database initialization attempt {attempt}/{max_retries}")
            
            # Initialize database connection
            db.init_app(app)
            
            with app.app_context():
                # Validate connection first
                db.engine.connect()
                
                # Create tables
                db.create_all()
                
                # Mark as available
                DB_AVAILABLE = True
                
                # Sync with telegram_handler
                try:
                    from telegram_handler import set_db_available
                    set_db_available(True)
                except ImportError:
                    logger.warning("Could not sync database status with telegram_handler")
                
                logger.info("Database tables created successfully")
                return
                
        except Exception as e:
            logger.error(f"Database initialization attempt {attempt} failed: {str(e)}")
            
            if attempt < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                logger.error("Database initialization failed after all retries")
                logger.warning("App will continue without database - some features will be disabled")

# Initialize database in background thread (non-blocking)
if DATABASE_URL:
    threading.Thread(target=init_database, daemon=True).start()
else:
    logger.info("Database initialization skipped - running without database")

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

@app.route('/health')
def health_check():
    """Comprehensive health check endpoint for deployment monitoring"""
    health_status = {
        "status": "healthy",
        "environment_valid": env_valid,
        "database": {
            "configured": DATABASE_URL is not None,
            "available": DB_AVAILABLE,
            "init_attempts": DB_INIT_ATTEMPTS
        },
        "bot_token_configured": BOT_TOKEN is not None,
        "timestamp": time.time()
    }
    
    # Return 503 if critical components are missing
    status_code = 200
    if not env_valid or not BOT_TOKEN:
        health_status["status"] = "degraded"
        status_code = 503
    elif DATABASE_URL and not DB_AVAILABLE:
        health_status["status"] = "degraded"
        health_status["database"]["message"] = "Database configured but not available"
    
    return jsonify(health_status), status_code

@app.route('/stats')
def stats():
    """Endpoint to view basic statistics about the bot usage"""
    if not DB_AVAILABLE:
        return jsonify({
            "error": "Database not available",
            "message": "Statistics require database connection"
        }), 503
    
    try:
        user_count = User.query.count()
        message_count = Message.query.count()
        recent_messages = Message.query.order_by(Message.created_at.desc()).limit(5).all()
        
        # Format recent messages for display
        recent_msgs_formatted = []
        for msg in recent_messages:
            user = User.query.get(msg.user_id)
            if user:
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

@app.route('/test_models', methods=['POST'])
def test_models():
    """Test endpoint to try both Grok and DeepSeek models on the same prompt"""
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({"error": "Request must include 'message' field"}), 400
            
        user_message = data['message']
        
        # Back up the current model
        current_model = os.environ.get('MODEL')
        
        # Test with Grok model
        os.environ['MODEL'] = 'grok-2-1212'
        from llm_api import call_grok_api
        grok_response = call_grok_api(user_message)
        
        # Test with DeepSeek model
        os.environ['MODEL'] = 'deepseek-ai/deepseek-chat-32b'
        from llm_api import call_deepseek_api
        deepseek_response = call_deepseek_api(user_message)
        
        # Restore the original model
        if current_model:
            os.environ['MODEL'] = current_model
        
        return jsonify({
            "status": "success",
            "user_message": user_message,
            "grok_response": grok_response,
            "deepseek_response": deepseek_response
        })
    except Exception as e:
        logger.error(f"Error in test_models endpoint: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Run the Flask application
    # Note: keepalive thread is already started in global scope
    app.run(host='0.0.0.0', port=5000, debug=True)
