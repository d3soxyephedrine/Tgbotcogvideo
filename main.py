import os
import logging
import threading
import time
import requests
import json
import hmac
import hashlib
from flask import Flask, request, jsonify, render_template_string
from telegram_handler import process_update, send_message
from llm_api import generate_response
from models import db, User, Message, Payment, Transaction, CryptoPayment
from datetime import datetime
from nowpayments_api import NOWPaymentsAPI

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
    optional_vars = ["DATABASE_URL", "XAI_API_KEY", "OPENROUTER_API_KEY", "MODEL", "SESSION_SECRET"]
    
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

# Initialize NOWPayments
NOWPAYMENTS_API_KEY = os.environ.get("NOWPAYMENTS_API_KEY")
if NOWPAYMENTS_API_KEY:
    nowpayments = NOWPaymentsAPI(NOWPAYMENTS_API_KEY)
    logger.info("NOWPayments API configured")
else:
    nowpayments = None
    logger.warning("NOWPAYMENTS_API_KEY not set - crypto payment features will be disabled")

NOWPAYMENTS_IPN_SECRET = os.environ.get("NOWPAYMENTS_IPN_SECRET")
if NOWPAYMENTS_IPN_SECRET:
    logger.info("NOWPayments IPN secret configured")
else:
    logger.warning("NOWPAYMENTS_IPN_SECRET not set - IPN callbacks will not be verified")

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

def verify_nowpayments_ipn(ipn_secret, callback_data, received_signature):
    """
    Verify NOWPayments IPN callback signature using HMAC-SHA512
    
    Args:
        ipn_secret (str): IPN secret key from NOWPayments
        callback_data (dict): JSON data from callback
        received_signature (str): Signature from x-nowpayments-sig header
    
    Returns:
        bool: True if signature is valid, False otherwise
    """
    try:
        sorted_json = json.dumps(callback_data, separators=(',', ':'), sort_keys=True)
        
        signature = hmac.new(
            ipn_secret.encode('utf-8'),
            sorted_json.encode('utf-8'),
            hashlib.sha512
        ).hexdigest()
        
        return hmac.compare_digest(signature, received_signature)
    except Exception as e:
        logger.error(f"IPN signature verification error: {str(e)}")
        return False

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

@app.route('/api/crypto/currencies', methods=['GET'])
def get_crypto_currencies():
    """Get list of available cryptocurrencies"""
    if not nowpayments:
        return jsonify({"error": "Crypto payments not configured"}), 503
    
    try:
        currencies = nowpayments.currencies()
        return jsonify({"currencies": currencies}), 200
    except Exception as e:
        logger.error(f"Error fetching crypto currencies: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/crypto/create-payment', methods=['POST'])
def create_crypto_payment():
    """Create a crypto payment using NOWPayments"""
    if not nowpayments:
        return jsonify({"error": "Crypto payments not configured"}), 503
    
    if not DB_AVAILABLE:
        return jsonify({"error": "Database not available"}), 503
    
    try:
        data = request.get_json()
        if not data or 'credits' not in data or 'pay_currency' not in data:
            return jsonify({"error": "Request must include 'credits' and 'pay_currency' fields"}), 400
        
        credits = int(data['credits'])
        pay_currency = data['pay_currency']
        user_telegram_id = data.get('telegram_id')
        
        if credits <= 0:
            return jsonify({"error": "Credits must be a positive number"}), 400
        
        if not user_telegram_id:
            return jsonify({"error": "telegram_id is required"}), 400
        
        # Calculate amount in USD ($0.10 per credit)
        price_amount = credits * 0.10
        
        # Get or create user
        user = User.query.filter_by(telegram_id=user_telegram_id).first()
        if not user:
            logger.warning(f"User {user_telegram_id} not found, creating new user")
            user = User(telegram_id=user_telegram_id)
            db.session.add(user)
            db.session.commit()
        
        # Generate unique order ID
        order_id = f"crypto_order_{user_telegram_id}_{int(datetime.utcnow().timestamp())}"
        
        # Get domain for IPN callback
        domain = os.environ.get("REPLIT_DEV_DOMAIN") or os.environ.get("REPLIT_DOMAINS", "").split(',')[0] if os.environ.get("REPLIT_DOMAINS") else None
        
        if not domain:
            logger.error("No domain configured for IPN callback")
            return jsonify({"error": "Domain not configured"}), 500
        
        if not domain.startswith('http'):
            domain = f"https://{domain}"
        
        logger.info(f"Creating crypto payment for {credits} credits (${price_amount:.2f}) in {pay_currency} for user {user_telegram_id}")
        
        # Create payment via NOWPayments
        payment_response = nowpayments.create_payment(
            price_amount=price_amount,
            price_currency='usd',
            pay_currency=pay_currency.lower(),
            ipn_callback_url=f"{domain}/api/crypto/ipn",
            order_id=order_id,
            order_description=f'Purchase {credits} credits for AI chat bot'
        )
        
        # Create CryptoPayment record in database
        crypto_payment = CryptoPayment(
            user_id=user.id,
            payment_id=payment_response['payment_id'],
            order_id=order_id,
            credits_purchased=credits,
            price_amount=price_amount,
            price_currency='USD',
            pay_amount=payment_response.get('pay_amount'),
            pay_currency=pay_currency.upper(),
            pay_address=payment_response.get('pay_address'),
            payment_status=payment_response.get('payment_status', 'waiting')
        )
        db.session.add(crypto_payment)
        db.session.commit()
        
        logger.info(f"Created crypto payment record {crypto_payment.id} with payment_id {payment_response['payment_id']}")
        
        return jsonify({
            "success": True,
            "payment_id": payment_response['payment_id'],
            "pay_address": payment_response['pay_address'],
            "pay_amount": payment_response['pay_amount'],
            "pay_currency": pay_currency.upper(),
            "payment_status": payment_response.get('payment_status'),
            "order_id": order_id
        }), 200
        
    except Exception as e:
        logger.error(f"Error creating crypto payment: {str(e)}")
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/api/crypto/ipn', methods=['POST'])
def crypto_ipn_callback():
    """Handle IPN (Instant Payment Notification) callbacks from NOWPayments with signature verification"""
    if not nowpayments:
        return jsonify({"error": "Crypto payments not configured"}), 503
    
    if not DB_AVAILABLE:
        logger.error("Database not available for IPN processing")
        return 'OK', 200
    
    try:
        received_signature = request.headers.get('x-nowpayments-sig')
        
        if not received_signature:
            logger.error("IPN callback missing x-nowpayments-sig header")
            return 'Missing signature', 401
        
        if not NOWPAYMENTS_IPN_SECRET:
            logger.error("NOWPAYMENTS_IPN_SECRET not configured - cannot verify IPN")
            return 'Configuration error', 500
        
        data = request.get_json()
        logger.info(f"Received crypto IPN callback: {data}")
        
        if not verify_nowpayments_ipn(NOWPAYMENTS_IPN_SECRET, data, received_signature):
            logger.error("IPN signature verification failed - rejecting callback")
            return 'Invalid signature', 401
        
        logger.info("IPN signature verified successfully")
        
        payment_id = data.get('payment_id')
        payment_status = data.get('payment_status')
        order_id = data.get('order_id')
        
        if not payment_id:
            logger.error("IPN callback missing payment_id")
            return 'Error', 400
        
        crypto_payment = CryptoPayment.query.filter_by(payment_id=payment_id).first()
        
        if not crypto_payment:
            logger.error(f"Crypto payment {payment_id} not found in database")
            return 'OK', 200
        
        if order_id and crypto_payment.order_id != order_id:
            logger.error(f"Order ID mismatch: expected {crypto_payment.order_id}, got {order_id}")
            return 'Order ID mismatch', 400
        
        if 'price_amount' in data:
            reported_price = float(data.get('price_amount'))
            if abs(reported_price - crypto_payment.price_amount) > 0.01:
                logger.error(f"Price amount mismatch: expected {crypto_payment.price_amount}, got {reported_price}")
                return 'Price mismatch', 400
        
        old_status = crypto_payment.payment_status
        crypto_payment.payment_status = payment_status
        
        logger.info(f"Crypto payment {payment_id} status updated from {old_status} to {payment_status}")
        
        if payment_status == 'finished' and old_status != 'finished':
            user = User.query.get(crypto_payment.user_id)
            if user:
                user.credits += crypto_payment.credits_purchased
                
                transaction = Transaction(
                    user_id=user.id,
                    credits_used=-crypto_payment.credits_purchased,
                    transaction_type='crypto_purchase',
                    description=f'Purchased {crypto_payment.credits_purchased} credits via {crypto_payment.pay_currency}'
                )
                db.session.add(transaction)
                
                logger.info(f"Added {crypto_payment.credits_purchased} credits to user {user.telegram_id}. New balance: {user.credits}")
                
                try:
                    confirmation_msg = f"✅ Payment confirmed! {crypto_payment.credits_purchased} credits have been added to your account.\n\nNew balance: {user.credits} credits"
                    send_message(user.telegram_id, confirmation_msg)
                except Exception as msg_error:
                    logger.error(f"Error sending confirmation message: {str(msg_error)}")
        
        elif payment_status == 'failed':
            logger.warning(f"Crypto payment {payment_id} failed")
            try:
                user = User.query.get(crypto_payment.user_id)
                if user:
                    send_message(user.telegram_id, "❌ Payment failed. Please try again or contact support.")
            except Exception as msg_error:
                logger.error(f"Error sending failure message: {str(msg_error)}")
        
        db.session.commit()
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"Error processing crypto IPN callback: {str(e)}")
        db.session.rollback()
        return 'Error', 500

@app.route('/api/crypto/payment-status/<payment_id>', methods=['GET'])
def get_crypto_payment_status(payment_id):
    """Check status of a crypto payment"""
    if not nowpayments:
        return jsonify({"error": "Crypto payments not configured"}), 503
    
    if not DB_AVAILABLE:
        return jsonify({"error": "Database not available"}), 503
    
    try:
        # Get from database
        crypto_payment = CryptoPayment.query.filter_by(payment_id=payment_id).first()
        
        if not crypto_payment:
            return jsonify({"error": "Payment not found"}), 404
        
        # Also check with NOWPayments API for latest status
        try:
            api_status = nowpayments.payment_status(payment_id)
            
            # Update database if status changed
            if api_status.get('payment_status') != crypto_payment.payment_status:
                crypto_payment.payment_status = api_status.get('payment_status')
                db.session.commit()
        except Exception as api_error:
            logger.error(f"Error fetching status from NOWPayments API: {str(api_error)}")
        
        return jsonify({
            "success": True,
            "payment_id": crypto_payment.payment_id,
            "payment_status": crypto_payment.payment_status,
            "pay_address": crypto_payment.pay_address,
            "pay_amount": crypto_payment.pay_amount,
            "pay_currency": crypto_payment.pay_currency,
            "credits_purchased": crypto_payment.credits_purchased
        }), 200
        
    except Exception as e:
        logger.error(f"Error checking crypto payment status: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/buy-credits', methods=['GET'])
def buy_credits_page():
    """Display credit purchase page with package options"""
    telegram_id = request.args.get('telegram_id')
    
    if not telegram_id:
        return render_template_string("""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Error - Purchase Credits</title>
                <style>
                    body {
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        min-height: 100vh;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        margin: 0;
                        padding: 20px;
                    }
                    .container {
                        background: white;
                        border-radius: 20px;
                        padding: 40px;
                        max-width: 500px;
                        width: 100%;
                        text-align: center;
                        box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                    }
                    .error-icon {
                        font-size: 64px;
                        color: #d32f2f;
                        margin-bottom: 20px;
                    }
                    h1 {
                        color: #d32f2f;
                        margin: 0 0 10px 0;
                    }
                    p {
                        color: #666;
                        line-height: 1.6;
                    }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="error-icon">⚠️</div>
                    <h1>Missing User ID</h1>
                    <p>Please access this page from the Telegram bot using the /buy command.</p>
                </div>
            </body>
            </html>
        """), 400
    
    html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Purchase Credits - AI Bot</title>
            <style>
                * {{
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }}
                
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 20px;
                }}
                
                .container {{
                    background: white;
                    border-radius: 20px;
                    padding: 40px;
                    max-width: 800px;
                    width: 100%;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                }}
                
                h1 {{
                    color: #333;
                    text-align: center;
                    margin-bottom: 10px;
                    font-size: 32px;
                }}
                
                .subtitle {{
                    text-align: center;
                    color: #666;
                    margin-bottom: 40px;
                    font-size: 16px;
                }}
                
                .packages {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                    gap: 20px;
                    margin-top: 30px;
                }}
                
                .package {{
                    background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                    border-radius: 15px;
                    padding: 30px;
                    text-align: center;
                    transition: transform 0.3s, box-shadow 0.3s;
                    cursor: pointer;
                    border: 3px solid transparent;
                }}
                
                .package:hover {{
                    transform: translateY(-5px);
                    box-shadow: 0 10px 30px rgba(0,0,0,0.15);
                    border-color: #667eea;
                }}
                
                .package.popular {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                }}
                
                .package.popular .credits {{
                    color: white;
                }}
                
                .package.popular .price {{
                    color: #f0f0f0;
                }}
                
                .badge {{
                    background: #fbbf24;
                    color: #78350f;
                    padding: 4px 12px;
                    border-radius: 12px;
                    font-size: 12px;
                    font-weight: bold;
                    display: inline-block;
                    margin-bottom: 10px;
                }}
                
                .credits {{
                    font-size: 48px;
                    font-weight: bold;
                    color: #667eea;
                    margin: 10px 0;
                }}
                
                .credits-label {{
                    font-size: 14px;
                    color: #666;
                    margin-bottom: 15px;
                }}
                
                .package.popular .credits-label {{
                    color: #f0f0f0;
                }}
                
                .price {{
                    font-size: 28px;
                    font-weight: bold;
                    color: #333;
                    margin: 15px 0;
                }}
                
                .per-credit {{
                    font-size: 12px;
                    color: #999;
                    margin-bottom: 20px;
                }}
                
                .package.popular .per-credit {{
                    color: #e0e0e0;
                }}
                
                .btn {{
                    background: #667eea;
                    color: white;
                    border: none;
                    padding: 12px 24px;
                    border-radius: 8px;
                    font-size: 16px;
                    font-weight: 600;
                    cursor: pointer;
                    width: 100%;
                    transition: background 0.3s;
                }}
                
                .btn:hover {{
                    background: #5568d3;
                }}
                
                .package.popular .btn {{
                    background: white;
                    color: #667eea;
                }}
                
                .package.popular .btn:hover {{
                    background: #f0f0f0;
                }}
                
                .info {{
                    background: #f0f9ff;
                    border-left: 4px solid #3b82f6;
                    padding: 15px;
                    margin-top: 30px;
                    border-radius: 5px;
                }}
                
                .info p {{
                    color: #1e40af;
                    margin: 5px 0;
                    font-size: 14px;
                }}
                
                .loading {{
                    display: none;
                    text-align: center;
                    margin-top: 20px;
                    color: #667eea;
                }}
                
                .loading.active {{
                    display: block;
                }}
                
                .payment-methods {{
                    margin-bottom: 40px;
                }}
                
                .method-buttons {{
                    display: flex;
                    gap: 15px;
                    justify-content: center;
                    flex-wrap: wrap;
                }}
                
                .method-btn {{
                    background: white;
                    border: 3px solid #e0e0e0;
                    border-radius: 12px;
                    padding: 15px 30px;
                    font-size: 18px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.3s;
                    color: #333;
                }}
                
                .method-btn:hover {{
                    border-color: #667eea;
                    transform: translateY(-2px);
                    box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                }}
                
                .method-btn.active {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border-color: #667eea;
                }}
                
                .crypto-selector {{
                    display: none;
                    margin-top: 15px;
                    text-align: center;
                }}
                
                .crypto-selector.show {{
                    display: block;
                }}
                
                .crypto-selector select {{
                    padding: 10px 20px;
                    border: 2px solid #667eea;
                    border-radius: 8px;
                    font-size: 16px;
                    background: white;
                    cursor: pointer;
                    min-width: 200px;
                }}
                
                #cryptoPaymentInfo {{
                    display: none;
                    background: #f8f9fa;
                    padding: 30px;
                    border-radius: 15px;
                    margin-top: 30px;
                    text-align: left;
                }}
                
                #cryptoPaymentInfo.show {{
                    display: block;
                }}
                
                .qr-code-container {{
                    text-align: center;
                    margin: 20px 0;
                }}
                
                .payment-address {{
                    background: white;
                    padding: 15px;
                    border-radius: 8px;
                    border: 2px solid #667eea;
                    word-break: break-all;
                    font-family: monospace;
                    margin: 10px 0;
                }}
                
                .copy-btn {{
                    background: #667eea;
                    color: white;
                    border: none;
                    padding: 10px 20px;
                    border-radius: 8px;
                    cursor: pointer;
                    margin-top: 10px;
                }}
                
                .copy-btn:hover {{
                    background: #5568d3;
                }}
                
                .status-badge {{
                    display: inline-block;
                    padding: 5px 15px;
                    border-radius: 20px;
                    font-weight: bold;
                    margin: 10px 0;
                }}
                
                .status-waiting {{ background: #ffc107; color: #000; }}
                .status-confirming {{ background: #2196F3; color: white; }}
                .status-confirmed {{ background: #4CAF50; color: white; }}
                .status-finished {{ background: #00c853; color: white; }}
                .status-failed {{ background: #f44336; color: white; }}
                
                @media (max-width: 768px) {{
                    .container {{
                        padding: 20px;
                    }}
                    
                    h1 {{
                        font-size: 24px;
                    }}
                    
                    .packages {{
                        grid-template-columns: 1fr;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>💳 Purchase Credits</h1>
                <p class="subtitle">Choose a package to power your AI conversations</p>
                
                <div class="payment-methods">
                    <h2 style="text-align: center; margin-bottom: 20px; color: #333;">Pay with Cryptocurrency</h2>
                    <div style="text-align: center;">
                        <label for="cryptoCurrency" style="font-size: 16px; margin-right: 10px;">Select Cryptocurrency:</label>
                        <select id="cryptoCurrency">
                            <option value="">Loading...</option>
                        </select>
                    </div>
                </div>
                
                <div class="packages">
                    <div class="package" onclick="handlePurchase(10)">
                        <div class="credits">10</div>
                        <div class="credits-label">Credits</div>
                        <div class="price">$1.00</div>
                        <div class="per-credit">$0.10 per credit</div>
                        <button class="btn">Get Started</button>
                    </div>
                    
                    <div class="package popular" onclick="handlePurchase(50)">
                        <div class="badge">POPULAR</div>
                        <div class="credits">50</div>
                        <div class="credits-label">Credits</div>
                        <div class="price">$5.00</div>
                        <div class="per-credit">$0.10 per credit</div>
                        <button class="btn">Best Value</button>
                    </div>
                    
                    <div class="package" onclick="handlePurchase(100)">
                        <div class="credits">100</div>
                        <div class="credits-label">Credits</div>
                        <div class="price">$10.00</div>
                        <div class="per-credit">$0.10 per credit</div>
                        <button class="btn">Power User</button>
                    </div>
                </div>
                
                <div id="cryptoPaymentInfo">
                    <h2>⏳ Awaiting Payment</h2>
                    <p><strong>Credits:</strong> <span id="cryptoCredits"></span></p>
                    <p><strong>Amount to Pay:</strong> <span id="cryptoAmount"></span> <span id="cryptoCurrency"></span></p>
                    <p><strong>Payment Address:</strong></p>
                    <div class="payment-address" id="cryptoAddress"></div>
                    <button class="copy-btn" onclick="copyAddress()">📋 Copy Address</button>
                    <p><strong>Status:</strong> <span class="status-badge" id="cryptoStatus"></span></p>
                    <p style="margin-top: 20px; color: #666;">Send the exact amount to the address above. Your credits will be added automatically once the payment is confirmed.</p>
                    <button onclick="checkPaymentStatus()" style="margin-top: 20px; padding: 10px 20px; background: #667eea; color: white; border: none; border-radius: 8px; cursor: pointer;">🔄 Check Status</button>
                </div>
                
                <div class="info">
                    <p>💡 <strong>What are credits?</strong></p>
                    <p>Each AI message costs 1 credit. Credits are used to access our uncensored AI models.</p>
                    <p>🔒 Secure crypto payments powered by NOWPayments</p>
                </div>
                
                <div class="loading" id="loading">
                    <p>🔄 Creating secure checkout session...</p>
                </div>
            </div>
            
            <script>
                let currentPaymentId = null;
                let statusCheckInterval = null;
                let availableCryptocurrencies = [];
                
                async function loadCryptocurrencies() {{
                    try {{
                        const response = await fetch('/api/crypto/currencies');
                        const data = await response.json();
                        
                        if (data.currencies && data.currencies.length > 0) {{
                            availableCryptocurrencies = data.currencies;
                            const select = document.getElementById('cryptoCurrency');
                            select.innerHTML = '<option value="">Select a cryptocurrency...</option>';
                            
                            const popular = ['btc', 'eth', 'usdt', 'ltc', 'bnb'];
                            popular.forEach(crypto => {{
                                if (data.currencies.includes(crypto)) {{
                                    const option = document.createElement('option');
                                    option.value = crypto;
                                    option.textContent = crypto.toUpperCase();
                                    select.appendChild(option);
                                }}
                            }});
                            
                            const separator = document.createElement('option');
                            separator.disabled = true;
                            separator.textContent = '──────────';
                            select.appendChild(separator);
                            
                            data.currencies.forEach(crypto => {{
                                if (!popular.includes(crypto)) {{
                                    const option = document.createElement('option');
                                    option.value = crypto;
                                    option.textContent = crypto.toUpperCase();
                                    select.appendChild(option);
                                }}
                            }});
                        }}
                    }} catch (error) {{
                        console.error('Error loading cryptocurrencies:', error);
                        document.getElementById('cryptoCurrency').innerHTML = '<option value="">Error loading currencies</option>';
                    }}
                }}
                
                loadCryptocurrencies();
                
                function handlePurchase(credits) {{
                    const selectedCrypto = document.getElementById('cryptoCurrency').value;
                    if (!selectedCrypto) {{
                        alert('Please select a cryptocurrency first');
                        return;
                    }}
                    purchaseWithCrypto(credits, selectedCrypto);
                }}
                
                async function purchaseWithCrypto(credits, payCurrency) {{
                    try {{
                        const response = await fetch('/api/crypto/create-payment', {{
                            method: 'POST',
                            headers: {{
                                'Content-Type': 'application/json'
                            }},
                            body: JSON.stringify({{
                                credits: credits,
                                pay_currency: payCurrency,
                                telegram_id: '{telegram_id}'
                            }})
                        }});
                        
                        const data = await response.json();
                        
                        if (data.success) {{
                            currentPaymentId = data.payment_id;
                            
                            document.getElementById('cryptoCredits').textContent = credits;
                            document.getElementById('cryptoAmount').textContent = data.pay_amount;
                            document.getElementById('cryptoCurrency').textContent = data.pay_currency;
                            document.getElementById('cryptoAddress').textContent = data.pay_address;
                            updatePaymentStatus(data.payment_status);
                            
                            document.getElementById('cryptoPaymentInfo').classList.add('show');
                            
                            if (statusCheckInterval) {{
                                clearInterval(statusCheckInterval);
                            }}
                            statusCheckInterval = setInterval(checkPaymentStatus, 10000);
                            
                            document.getElementById('cryptoPaymentInfo').scrollIntoView({{ behavior: 'smooth' }});
                        }} else {{
                            alert('Error creating payment: ' + (data.error || 'Unknown error'));
                        }}
                    }} catch (error) {{
                        console.error('Error:', error);
                        alert('Error creating crypto payment. Please try again.');
                    }}
                }}
                
                async function checkPaymentStatus() {{
                    if (!currentPaymentId) return;
                    
                    try {{
                        const response = await fetch(`/api/crypto/payment-status/${{currentPaymentId}}`);
                        const data = await response.json();
                        
                        if (data.success) {{
                            updatePaymentStatus(data.payment_status);
                            
                            if (data.payment_status === 'finished') {{
                                clearInterval(statusCheckInterval);
                                alert('Payment confirmed! Your credits have been added.');
                                setTimeout(() => {{
                                    window.location.reload();
                                }}, 2000);
                            }} else if (data.payment_status === 'failed') {{
                                clearInterval(statusCheckInterval);
                                alert('Payment failed. Please try again.');
                            }}
                        }}
                    }} catch (error) {{
                        console.error('Error checking payment status:', error);
                    }}
                }}
                
                function updatePaymentStatus(status) {{
                    const statusElement = document.getElementById('cryptoStatus');
                    statusElement.textContent = status.toUpperCase();
                    statusElement.className = 'status-badge status-' + status;
                }}
                
                function copyAddress() {{
                    const address = document.getElementById('cryptoAddress').textContent;
                    navigator.clipboard.writeText(address).then(() => {{
                        const btn = event.target;
                        const originalText = btn.textContent;
                        btn.textContent = '✓ Copied!';
                        setTimeout(() => {{
                            btn.textContent = originalText;
                        }}, 2000);
                    }});
                }}
            </script>
        </body>
        </html>
    """
    
    return render_template_string(html), 200

@app.route('/payment-history')
def payment_history():
    """View payment history for a user (debugging endpoint)"""
    if not DB_AVAILABLE:
        return jsonify({
            "error": "Database not available",
            "message": "Payment history requires database connection"
        }), 503
    
    telegram_id = request.args.get('telegram_id')
    
    if not telegram_id:
        return jsonify({"error": "telegram_id query parameter is required"}), 400
    
    try:
        telegram_id = int(telegram_id)
        user = User.query.filter_by(telegram_id=telegram_id).first()
        
        if not user:
            return jsonify({
                "error": "User not found",
                "telegram_id": telegram_id
            }), 404
        
        payments = Payment.query.filter_by(user_id=user.id).order_by(Payment.created_at.desc()).all()
        
        payment_list = []
        for payment in payments:
            payment_list.append({
                "id": payment.id,
                "amount_cents": payment.amount,
                "amount_dollars": payment.amount / 100,
                "credits_purchased": payment.credits_purchased,
                "status": payment.status,
                "created_at": payment.created_at.strftime("%Y-%m-%d %H:%M:%S") if payment.created_at else None,
                "completed_at": payment.completed_at.strftime("%Y-%m-%d %H:%M:%S") if payment.completed_at else None,
                "stripe_session_id": payment.stripe_session_id
            })
        
        return jsonify({
            "user": {
                "telegram_id": user.telegram_id,
                "username": user.username,
                "current_credits": user.credits
            },
            "payments": payment_list,
            "total_payments": len(payment_list)
        }), 200
        
    except ValueError:
        return jsonify({"error": "Invalid telegram_id format"}), 400
    except Exception as e:
        logger.error(f"Error retrieving payment history: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Run the Flask application
    # Note: keepalive thread is already started in global scope
    app.run(host='0.0.0.0', port=5000, debug=True)
