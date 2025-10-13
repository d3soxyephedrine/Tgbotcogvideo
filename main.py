import os
import logging
import threading
import time
import requests
import json
import hmac
import hashlib
from flask import Flask, request, jsonify, render_template_string
from telegram_handler import process_update, send_message, scan_and_filter_output
from llm_api import generate_response
from models import db, User, Message, Payment, Transaction, CryptoPayment
from datetime import datetime
from nowpayments_api import NOWPaymentsAPI
from nowpayments_wrapper import NOWPaymentsWrapper

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

# Initialize database synchronously (blocking) to ensure DB_AVAILABLE is set before handling requests
if DATABASE_URL:
    init_database()
else:
    logger.info("Database initialization skipped - running without database")

# Get environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable is not set!")

# Initialize NOWPayments with custom wrapper
NOWPAYMENTS_API_KEY = os.environ.get("NOWPAYMENTS_API_KEY")
if NOWPAYMENTS_API_KEY:
    nowpayments = NOWPaymentsWrapper(NOWPAYMENTS_API_KEY)
    logger.info("NOWPayments API configured (using custom wrapper)")
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

def verify_nowpayments_ipn(ipn_secret, raw_body_bytes, received_signature):
    """
    Verify NOWPayments IPN callback signature using HMAC-SHA512
    
    Args:
        ipn_secret (str): IPN secret key from NOWPayments
        raw_body_bytes (bytes): Raw request body as bytes (not re-serialized JSON)
        received_signature (str): Signature from x-nowpayments-sig header
    
    Returns:
        bool: True if signature is valid, False otherwise
    """
    try:
        # Calculate HMAC-SHA512 signature on the raw request body bytes
        # CRITICAL: Must use raw body exactly as received, not re-serialized JSON
        signature = hmac.new(
            ipn_secret.encode('utf-8'),
            raw_body_bytes,
            hashlib.sha512
        ).hexdigest()
        
        # Normalize both signatures (strip whitespace, lowercase) before comparison
        computed_sig = signature.strip().lower()
        received_sig = received_signature.strip().lower()
        
        # Use constant-time comparison to prevent timing attacks
        return hmac.compare_digest(computed_sig, received_sig)
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
        # Get domain from environment or request parameter
        url = request.args.get('url')
        if not url:
            # Try to auto-detect domain from Replit environment
            domain = os.environ.get("REPLIT_DOMAINS", "").split(',')[0] if os.environ.get("REPLIT_DOMAINS") else os.environ.get("REPLIT_DEV_DOMAIN")
            if domain:
                if not domain.startswith('http'):
                    url = f"https://{domain}"
                else:
                    url = domain
            else:
                return jsonify({"error": "URL parameter is required or REPLIT_DOMAINS must be set"}), 400
            
        webhook_url = f"{url}/{BOT_TOKEN}"
        telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
        
        # Make the actual request to Telegram
        response = requests.get(telegram_url)
        response_data = response.json()
        
        if response_data.get('ok'):
            logger.info(f"Webhook set successfully to: {webhook_url}")
            return jsonify({
                "success": True,
                "message": "Webhook set successfully",
                "webhook_url": webhook_url,
                "telegram_response": response_data
            })
        else:
            logger.error(f"Failed to set webhook: {response_data}")
            return jsonify({
                "success": False,
                "error": "Failed to set webhook",
                "telegram_response": response_data
            }), 400
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
        
        # Filter output to prevent prompt leakage
        response = scan_and_filter_output(response)
        
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
        
        # Filter both responses to prevent prompt leakage
        grok_response = scan_and_filter_output(grok_response)
        deepseek_response = scan_and_filter_output(deepseek_response)
        
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

@app.route('/buy', methods=['GET'])
def buy_credits_page():
    """Buy credits page - displays credit packages and payment options"""
    telegram_id = request.args.get('telegram_id', '')
    
    if not telegram_id:
        return "Error: telegram_id parameter is required", 400
    
    html = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Buy Credits</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                   background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                   min-height: 100vh; padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; background: white; 
                         border-radius: 20px; padding: 30px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }}
            h1 {{ color: #333; margin-bottom: 10px; text-align: center; }}
            .subtitle {{ color: #666; text-align: center; margin-bottom: 30px; font-size: 14px; }}
            .packages {{ display: grid; gap: 15px; margin-bottom: 25px; }}
            .package {{ border: 2px solid #e0e0e0; border-radius: 12px; padding: 20px; 
                       cursor: pointer; transition: all 0.3s; position: relative; }}
            .package:hover {{ border-color: #667eea; transform: translateY(-2px); 
                            box-shadow: 0 5px 15px rgba(102,126,234,0.2); }}
            .package.selected {{ border-color: #667eea; background: #f8f9ff; }}
            .package-title {{ font-size: 20px; font-weight: bold; color: #333; margin-bottom: 5px; }}
            .package-price {{ font-size: 28px; font-weight: bold; color: #667eea; margin-bottom: 5px; }}
            .package-desc {{ color: #666; font-size: 14px; }}
            .form-group {{ margin-bottom: 20px; }}
            label {{ display: block; margin-bottom: 8px; font-weight: 600; color: #333; }}
            select {{ width: 100%; padding: 12px; border: 2px solid #e0e0e0; border-radius: 8px; 
                     font-size: 16px; transition: border-color 0.3s; }}
            select:focus {{ outline: none; border-color: #667eea; }}
            button {{ width: 100%; padding: 15px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                     color: white; border: none; border-radius: 8px; font-size: 18px; font-weight: bold; 
                     cursor: pointer; transition: transform 0.2s; }}
            button:hover {{ transform: translateY(-2px); }}
            button:disabled {{ opacity: 0.6; cursor: not-allowed; }}
            .result {{ margin-top: 20px; padding: 15px; border-radius: 8px; display: none; }}
            .result.success {{ background: #d4edda; border: 1px solid #c3e6cb; color: #155724; }}
            .result.error {{ background: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }}
            .payment-info {{ margin-top: 15px; }}
            .payment-info div {{ margin-bottom: 10px; padding: 10px; background: #f8f9fa; 
                                border-radius: 5px; word-break: break-all; }}
            .payment-info strong {{ display: block; margin-bottom: 5px; color: #667eea; }}
            .loading {{ text-align: center; padding: 15px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>💎 Buy Credits</h1>
            <p class="subtitle">Select a package and pay with cryptocurrency</p>
            
            <div class="packages" id="packages">
                <div class="package" data-credits="200" data-price="20">
                    <div class="package-title">Starter Pack</div>
                    <div class="package-price">$20</div>
                    <div class="package-desc">200 credits • $0.10 per credit</div>
                </div>
                <div class="package" data-credits="500" data-price="40">
                    <div class="package-title">Popular Pack</div>
                    <div class="package-price">$40</div>
                    <div class="package-desc">500 credits • $0.08 per credit</div>
                </div>
                <div class="package" data-credits="1000" data-price="60">
                    <div class="package-title">Value Pack</div>
                    <div class="package-price">$60</div>
                    <div class="package-desc">1000 credits • $0.06 per credit</div>
                </div>
            </div>
            
            <div class="form-group">
                <label for="currency">Payment Currency</label>
                <select id="currency">
                    <option value="">Loading currencies...</option>
                </select>
            </div>
            
            <button id="createPayment" onclick="createPayment()" disabled>Create Payment</button>
            
            <div id="result" class="result"></div>
        </div>
        
        <script>
            const telegramId = '{telegram_id}';
            let selectedPackage = null;
            
            // Package selection
            document.querySelectorAll('.package').forEach(pkg => {{
                pkg.addEventListener('click', () => {{
                    document.querySelectorAll('.package').forEach(p => p.classList.remove('selected'));
                    pkg.classList.add('selected');
                    selectedPackage = {{
                        credits: parseInt(pkg.dataset.credits),
                        price: parseFloat(pkg.dataset.price)
                    }};
                    updateButtonState();
                }});
            }});
            
            // Load currencies
            fetch('/api/crypto/currencies')
                .then(r => r.json())
                .then(data => {{
                    const select = document.getElementById('currency');
                    const currencies = data.currencies || [];
                    select.innerHTML = '<option value="">-- Select Currency --</option>' + 
                        currencies.map(c => `<option value="${{c}}">${{c.toUpperCase()}}</option>`).join('');
                    updateButtonState();
                }})
                .catch(err => {{
                    document.getElementById('currency').innerHTML = '<option value="">Error loading currencies</option>';
                }});
            
            function updateButtonState() {{
                const btn = document.getElementById('createPayment');
                const currency = document.getElementById('currency').value;
                btn.disabled = !selectedPackage || !currency;
            }}
            
            document.getElementById('currency').addEventListener('change', updateButtonState);
            
            async function createPayment() {{
                const resultDiv = document.getElementById('result');
                const button = document.getElementById('createPayment');
                const currency = document.getElementById('currency').value;
                
                if (!selectedPackage || !currency) {{
                    return;
                }}
                
                button.disabled = true;
                resultDiv.className = 'result';
                resultDiv.innerHTML = '<div class="loading">Creating payment...</div>';
                resultDiv.style.display = 'block';
                
                try {{
                    const response = await fetch('/api/crypto/create-payment', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{
                            telegram_id: telegramId,
                            credits: selectedPackage.credits,
                            pay_currency: currency
                        }})
                    }});
                    
                    const data = await response.json();
                    
                    if (data.success) {{
                        resultDiv.className = 'result success';
                        resultDiv.innerHTML = `
                            <h3>✅ Payment Created Successfully!</h3>
                            <div class="payment-info">
                                <div><strong>Payment ID:</strong> ${{data.payment_id}}</div>
                                <div><strong>Send ${{data.pay_amount}} ${{data.pay_currency}}</strong> to this address:</div>
                                <div style="font-family: monospace; font-size: 14px;"><strong>Address:</strong> ${{data.pay_address}}</div>
                                <div><strong>Status:</strong> ${{data.payment_status}}</div>
                                <div style="margin-top: 15px; padding: 10px; background: #fff3cd; border: 1px solid #ffeaa7; border-radius: 5px;">
                                    ⏳ Credits will be added automatically when payment is confirmed
                                </div>
                            </div>
                        `;
                    }} else {{
                        resultDiv.className = 'result error';
                        resultDiv.innerHTML = `<strong>❌ Error:</strong> ${{data.error || 'Payment creation failed'}}`;
                        button.disabled = false;
                    }}
                }} catch (err) {{
                    resultDiv.className = 'result error';
                    resultDiv.innerHTML = `<strong>❌ Error:</strong> ${{err.message}}`;
                    button.disabled = false;
                }}
            }}
        </script>
    </body>
    </html>
    '''
    
    return render_template_string(html)

@app.route('/api/crypto/currencies', methods=['GET'])
def get_crypto_currencies():
    """Get list of available cryptocurrencies"""
    if not nowpayments:
        return jsonify({"error": "Crypto payments not configured"}), 503
    
    try:
        currencies_response = nowpayments.currencies()
        # Extract the currencies array from the response
        if isinstance(currencies_response, dict) and 'currencies' in currencies_response:
            currencies = currencies_response['currencies']
        else:
            currencies = currencies_response
        return jsonify({"currencies": currencies}), 200
    except Exception as e:
        logger.error(f"Error fetching crypto currencies: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/crypto/minimum-amount', methods=['GET'])
def get_minimum_payment_amount():
    """Get minimum payment amount for a cryptocurrency"""
    if not nowpayments:
        return jsonify({"error": "Crypto payments not configured"}), 503
    
    try:
        currency = request.args.get('currency', 'btc')
        min_amount_data = nowpayments.minimum_payment_amount(currency_from='usd', currency_to=currency.lower())
        return jsonify(min_amount_data), 200
    except Exception as e:
        logger.error(f"Error fetching minimum payment amount: {str(e)}")
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
        
        # Convert telegram_id to integer (Telegram IDs are always numeric)
        try:
            user_telegram_id = int(user_telegram_id)
        except (ValueError, TypeError):
            return jsonify({"error": "telegram_id must be a valid number"}), 400
        
        # Calculate amount in USD based on credit package
        CREDIT_PACKAGES = {
            200: 10.0,
            500: 25.0,
            1000: 50.0
        }
        
        if credits not in CREDIT_PACKAGES:
            return jsonify({"error": f"Invalid credit amount. Valid options: {list(CREDIT_PACKAGES.keys())}"}), 400
        
        price_amount = CREDIT_PACKAGES[credits]
        
        # Check minimum payment amount
        try:
            min_amount_data = nowpayments.minimum_payment_amount(currency_from='usd', currency_to=pay_currency.lower())
            min_fiat_amount = float(min_amount_data.get('fiat_equivalent', 0))
            if price_amount < min_fiat_amount:
                # Find the smallest package that meets minimum
                suitable_packages = [c for c, p in CREDIT_PACKAGES.items() if p >= min_fiat_amount]
                min_package = min(suitable_packages) if suitable_packages else 200
                return jsonify({
                    "error": f"Amount too low. Minimum payment for {pay_currency.upper()} is ${min_fiat_amount:.2f}. Please select {min_package} credits package or higher."
                }), 400
        except Exception as e:
            logger.warning(f"Could not check minimum amount: {str(e)}")
        
        # Get or create user
        user = User.query.filter_by(telegram_id=user_telegram_id).first()
        if not user:
            logger.warning(f"User {user_telegram_id} not found, creating new user")
            user = User(telegram_id=user_telegram_id, credits=100)
            db.session.add(user)
            db.session.commit()
        
        # Generate unique order ID
        order_id = f"crypto_order_{user_telegram_id}_{int(datetime.utcnow().timestamp())}"
        
        # Get domain for IPN callback
        domain = os.environ.get("REPLIT_DOMAINS", "").split(',')[0] if os.environ.get("REPLIT_DOMAINS") else os.environ.get("REPLIT_DEV_DOMAIN")
        
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
        # Return 503 to trigger NOWPayments retry mechanism
        return 'Database unavailable', 503
    
    try:
        received_signature = request.headers.get('x-nowpayments-sig')
        
        if not received_signature:
            logger.error("IPN callback missing x-nowpayments-sig header")
            return 'Missing signature', 401
        
        if not NOWPAYMENTS_IPN_SECRET:
            logger.error("NOWPAYMENTS_IPN_SECRET not configured - cannot verify IPN")
            return 'Configuration error', 500
        
        # Get raw request body as bytes for signature verification
        # CRITICAL: Use cache=True to preserve body for JSON parsing
        raw_body_bytes = request.get_data(cache=True)
        
        if not verify_nowpayments_ipn(NOWPAYMENTS_IPN_SECRET, raw_body_bytes, received_signature):
            logger.error("IPN signature verification failed - rejecting callback")
            return 'Invalid signature', 401
        
        logger.info("IPN signature verified successfully")
        
        # Parse JSON from the same bytes after verification
        data = json.loads(raw_body_bytes.decode('utf-8'))
        logger.info(f"Received crypto IPN callback: {data}")
        
        payment_id = data.get('payment_id')
        payment_status = data.get('payment_status')
        order_id = data.get('order_id')
        
        if not payment_id:
            logger.error("IPN callback missing payment_id")
            return 'Error', 400
        
        # Lock the payment record for atomic update (prevents race conditions)
        crypto_payment = CryptoPayment.query.filter_by(payment_id=payment_id).with_for_update().first()
        
        if not crypto_payment:
            logger.error(f"Crypto payment {payment_id} not found in database - requesting retry")
            # Return 503 to trigger NOWPayments retry (payment might be created soon)
            return 'Payment not found', 503
        
        if order_id and crypto_payment.order_id != order_id:
            logger.error(f"Order ID mismatch: expected {crypto_payment.order_id}, got {order_id}")
            return 'Order ID mismatch', 400
        
        # Validate price amount matches expected (in USD/fiat)
        if 'price_amount' in data:
            reported_price = float(data.get('price_amount'))
            if abs(reported_price - crypto_payment.price_amount) > 0.01:
                logger.error(f"Price amount mismatch: expected ${crypto_payment.price_amount}, got ${reported_price}")
                return 'Price mismatch', 400
        
        # Validate pay currency matches
        if 'pay_currency' in data:
            reported_currency = data.get('pay_currency', '').upper()
            if crypto_payment.pay_currency and reported_currency != crypto_payment.pay_currency:
                logger.error(f"Pay currency mismatch: expected {crypto_payment.pay_currency}, got {reported_currency}")
                return 'Currency mismatch', 400
        
        old_status = crypto_payment.payment_status
        crypto_payment.payment_status = payment_status
        
        logger.info(f"Crypto payment {payment_id} status updated from {old_status} to {payment_status}")
        
        # Handle partial/underpaid status explicitly
        if payment_status in ['partially_paid', 'underpaid']:
            logger.warning(f"Payment {payment_id} is {payment_status}, not crediting")
            db.session.commit()
            return 'OK', 200
        
        # Add credits only when payment is finished AND credits haven't been added yet (atomic idempotency)
        if payment_status == 'finished' and not crypto_payment.credits_added:
            user = User.query.get(crypto_payment.user_id)
            if user:
                # Validate actually paid amount (if provided)
                # Use outcome_amount (fiat) for comparison with price_amount
                if 'outcome_amount' in data:
                    actually_paid_fiat = float(data.get('outcome_amount'))
                    if actually_paid_fiat < (crypto_payment.price_amount - 0.01):
                        logger.error(f"Underpayment detected: expected ${crypto_payment.price_amount}, received ${actually_paid_fiat}")
                        db.session.commit()
                        return 'Underpayment', 400
                
                # Add credits to user account
                user.credits += crypto_payment.credits_purchased
                
                # Create transaction record
                transaction = Transaction(
                    user_id=user.id,
                    credits_used=-crypto_payment.credits_purchased,
                    transaction_type='crypto_purchase',
                    description=f'Purchased {crypto_payment.credits_purchased} credits via {crypto_payment.pay_currency}'
                )
                db.session.add(transaction)
                
                # Mark as processed to prevent duplicate credits (idempotency)
                crypto_payment.credits_added = True
                crypto_payment.processed_at = datetime.utcnow()
                
                logger.info(f"Added {crypto_payment.credits_purchased} credits to user {user.telegram_id}. New balance: {user.credits}")
                
                # Commit before sending notification
                db.session.commit()
                
                # Send confirmation message after successful commit
                try:
                    confirmation_msg = f"✅ Payment confirmed! {crypto_payment.credits_purchased} credits have been added to your account.\n\nNew balance: {user.credits} credits"
                    send_message(user.telegram_id, confirmation_msg)
                except Exception as msg_error:
                    logger.error(f"Error sending confirmation message: {str(msg_error)}")
                
                return 'OK', 200
        elif payment_status == 'finished' and crypto_payment.credits_added:
            # Idempotency: Credits already added, just log and return success
            logger.info(f"Payment {payment_id} already processed at {crypto_payment.processed_at}. Skipping duplicate credit addition.")
            # Still commit to persist any status changes
            db.session.commit()
            return 'OK', 200
        
        elif payment_status == 'failed':
            logger.warning(f"Crypto payment {payment_id} failed")
            db.session.commit()
            try:
                user = User.query.get(crypto_payment.user_id)
                if user:
                    send_message(user.telegram_id, "❌ Payment failed. Please try again or contact support.")
            except Exception as msg_error:
                logger.error(f"Error sending failure message: {str(msg_error)}")
            return 'OK', 200
        
        db.session.commit()
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"Error processing crypto IPN callback: {str(e)}")
        db.session.rollback()
        # Return 503 to trigger NOWPayments retry mechanism
        return 'Server error - retry requested', 503

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
