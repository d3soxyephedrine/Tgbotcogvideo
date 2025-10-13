import os
import logging
import requests
from llm_api import generate_response, MODEL
from models import db, User, Message, Payment, Transaction
from datetime import datetime
from security import input_filter, output_scanner

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Flag to track database availability (will be set by main.py)
DB_AVAILABLE = False

def set_db_available(available):
    """Set database availability flag from main.py"""
    global DB_AVAILABLE
    DB_AVAILABLE = available

# Get environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_message(chat_id, text, parse_mode="Markdown"):
    """Send a message to a specific chat in Telegram
    
    Args:
        chat_id (int): The ID of the chat to send to
        text (str): The text message to send
        parse_mode (str | None): Parse mode for formatting (default: "Markdown", use None for plain text)
    
    Returns:
        dict: The response from Telegram API
    """
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not configured")
        return {"error": "Bot token not configured"}
    
    # Break long messages into chunks (Telegram has a 4096 character limit)
    if len(text) > 4000:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        responses = []
        
        for chunk in chunks:
            payload = {
                "chat_id": chat_id,
                "text": chunk
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode
                
            response = requests.post(
                f"{BASE_URL}/sendMessage",
                json=payload
            )
            responses.append(response.json())
        return responses
    
    # Send a normal message
    try:
        payload = {
            "chat_id": chat_id,
            "text": text
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
            
        response = requests.post(
            f"{BASE_URL}/sendMessage",
            json=payload
        )
        result = response.json()
        
        # Log errors for debugging
        if not result.get("ok"):
            logger.error(f"Telegram API error: {result}")
            
        return result
    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        return {"error": str(e)}

def get_help_message():
    """Get the help message with available commands"""
    help_text = """
🤖 *Uncensored AI Bot Commands* 🤖

/start - Start the bot
/help - Display this help message
/model - Show current model 
/model grok - Switch to Grok model
/model deepseek - Switch to DeepSeek model
/model chatgpt - Switch to GPT-4o Chat model
/balance - Check your credit balance
/buy - Purchase more credits

💡 *Each AI message costs 1 credit*

Send any message to get an uncensored AI response!
    """
    return help_text

def process_update(update):
    """Process an update from Telegram
    
    Args:
        update (dict): The update object from Telegram
    """
    # Check if the update contains a message
    if "message" not in update:
        logger.debug("Update does not contain a message")
        return
    
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    
    # Get user information
    user_info = message.get("from", {})
    telegram_id = user_info.get("id")
    username = user_info.get("username")
    first_name = user_info.get("first_name")
    last_name = user_info.get("last_name")
    
    # If no chat_id or empty text, ignore
    if not chat_id or not text:
        logger.debug(f"Missing chat_id or text: {chat_id}, {text}")
        return
    
    logger.debug(f"Processing message from chat {chat_id}: {text}")
    
    try:
        # First, send a "typing" action to indicate the bot is processing
        requests.post(
            f"{BASE_URL}/sendChatAction",
            json={
                "chat_id": chat_id,
                "action": "typing"
            }
        )
        
        # Store user in database if database is available
        user_id = None
        user = None
        if DB_AVAILABLE:
            try:
                from flask import current_app
                with current_app.app_context():
                    # Get or create user
                    user = User.query.filter_by(telegram_id=telegram_id).first()
                    if not user:
                        user = User(
                            telegram_id=telegram_id,
                            username=username,
                            first_name=first_name,
                            last_name=last_name,
                            credits=50
                        )
                        db.session.add(user)
                        db.session.commit()
                        logger.info(f"New user created: {user}")
                    else:
                        # Update last interaction
                        user.last_interaction = datetime.utcnow()
                        db.session.commit()
                    
                    user_id = user.id
            except Exception as db_error:
                logger.error(f"Database error while storing user: {str(db_error)}")
                logger.warning("Continuing without database storage")
        else:
            logger.debug("Skipping user storage - database not available")
        
        # Check credits for non-command messages
        if not text.startswith('/'):
            if DB_AVAILABLE and user:
                if user.credits <= 0:
                    response = "⚠️ You're out of credits!\n\nTo continue using the bot, please purchase more credits using the /buy command."
                    send_message(chat_id, response)
                    return
        
        # Check for /start or /help commands
        if text.lower() == '/start' or text.lower() == '/help':
            response = get_help_message()
            
            # Store command in database if available
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        message_record = Message(
                            user_id=user_id,
                            user_message=text,
                            bot_response=response,
                            model_used=os.environ.get('MODEL', MODEL),
                            credits_charged=0
                        )
                        db.session.add(message_record)
                        db.session.commit()
                except Exception as db_error:
                    logger.error(f"Database error storing command: {str(db_error)}")
            
            # Send response
            send_message(chat_id, response)
            return
        
        # Check for /balance or /credits commands
        if text.lower() == '/balance' or text.lower() == '/credits':
            if DB_AVAILABLE and user:
                credits = user.credits
                response = f"💳 Your credit balance: {credits} credits\n\nEach AI message costs 1 credit.\nUse /buy to purchase more credits."
            else:
                response = "💳 Credit system requires database access."
            
            # Store command in database if available
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        message_record = Message(
                            user_id=user_id,
                            user_message=text,
                            bot_response=response,
                            model_used=os.environ.get('MODEL', MODEL),
                            credits_charged=0
                        )
                        db.session.add(message_record)
                        db.session.commit()
                except Exception as db_error:
                    logger.error(f"Database error storing balance command: {str(db_error)}")
            
            # Send response
            send_message(chat_id, response)
            return
        
        # Check for /buy command
        if text.lower() == '/buy':
            # Get domain from environment variables
            domain = os.environ.get('REPLIT_DOMAINS', '').split(',')[0] if os.environ.get('REPLIT_DOMAINS') else os.environ.get('REPLIT_DEV_DOMAIN') or 'your-app.replit.app'
            
            response = f"""💰 Credit Packages

• 200 credits = $20.00
• 500 credits = $40.00
• 1000 credits = $60.00

To purchase credits, visit:
https://{domain}/buy?telegram_id={telegram_id}

Each AI message costs 1 credit.
"""
            
            # Store command in database if available
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        message_record = Message(
                            user_id=user_id,
                            user_message=text,
                            bot_response=response,
                            model_used=os.environ.get('MODEL', MODEL),
                            credits_charged=0
                        )
                        db.session.add(message_record)
                        db.session.commit()
                except Exception as db_error:
                    logger.error(f"Database error storing buy command: {str(db_error)}")
            
            # Send response without Markdown (URL causes parsing issues)
            send_message(chat_id, response, parse_mode=None)
            return
            
        # Check for model switch commands
        if text.lower().startswith('/model'):
            parts = text.split()
            if len(parts) > 1:
                model_name = parts[1].lower()
                
                # Process model change request
                if 'grok' in model_name:
                    os.environ['MODEL'] = 'grok-2-1212'
                    response = f"Model switched to Grok."
                elif 'deepseek' in model_name:
                    os.environ['MODEL'] = 'deepseek/deepseek-chat'
                    response = f"Model switched to DeepSeek."
                elif 'gpt' in model_name or 'chatgpt' in model_name:
                    os.environ['MODEL'] = 'openai/gpt-4o'
                    response = f"Model switched to GPT-4o."
                else:
                    response = f"Unknown model: {model_name}. Available models: grok, deepseek, chatgpt."
                    
                # Store command in database if available
                if DB_AVAILABLE and user_id:
                    try:
                        from flask import current_app
                        with current_app.app_context():
                            message_record = Message(
                                user_id=user_id,
                                user_message=text,
                                bot_response=response,
                                model_used=os.environ.get('MODEL', MODEL),
                                credits_charged=0
                            )
                            db.session.add(message_record)
                            db.session.commit()
                            logger.info(f"Model switch command stored: {message_record.id}")
                    except Exception as db_error:
                        logger.error(f"Database error storing model switch: {str(db_error)}")
                
                # Send response
                send_message(chat_id, response, parse_mode=None)
                return
            else:
                current_model = os.environ.get('MODEL', MODEL)
                response = f"Current model: {current_model}\nAvailable models: grok, deepseek, chatgpt\nTo switch, use /model <model_name>"
                
                # Store command in database if available
                if DB_AVAILABLE and user_id:
                    try:
                        from flask import current_app
                        with current_app.app_context():
                            message_record = Message(
                                user_id=user_id,
                                user_message=text,
                                bot_response=response,
                                model_used=current_model,
                                credits_charged=0
                            )
                            db.session.add(message_record)
                            db.session.commit()
                    except Exception as db_error:
                        logger.error(f"Database error storing model query: {str(db_error)}")
                
                # Send response
                send_message(chat_id, response, parse_mode=None)
                return
        
        # Apply input filtering to detect prompt extraction attempts
        is_safe, blocked_reason = input_filter(text)
        if not is_safe:
            logger.warning(f"Message blocked by input filter: {text[:100]}...")
            response = blocked_reason
            send_message(chat_id, response, parse_mode=None)
            return
        
        # Generate response from LLM
        current_model = os.environ.get('MODEL', MODEL)
        llm_response = generate_response(text)
        
        # Apply output scanning to detect leaked system prompt content
        sanitized_response, was_modified = output_scanner(llm_response)
        if was_modified:
            logger.error(f"Response was sanitized due to potential system prompt leak")
        
        # Use the sanitized response
        llm_response = sanitized_response
        
        # Store message and deduct credits if available
        if DB_AVAILABLE and user_id:
            try:
                from flask import current_app
                with current_app.app_context():
                    # Create message record
                    message_record = Message(
                        user_id=user_id,
                        user_message=text,
                        bot_response=llm_response,
                        model_used=current_model,
                        credits_charged=1
                    )
                    db.session.add(message_record)
                    db.session.flush()
                    
                    # Deduct 1 credit from user
                    user = User.query.get(user_id)
                    if user:
                        user.credits = max(0, user.credits - 1)
                    
                    # Create transaction record
                    transaction = Transaction(
                        user_id=user_id,
                        credits_used=1,
                        message_id=message_record.id,
                        transaction_type='message',
                        description=f"AI message response using {current_model}"
                    )
                    db.session.add(transaction)
                    
                    # Commit all changes
                    db.session.commit()
                    logger.info(f"Message stored, credits deducted: {message_record.id}")
            except Exception as db_error:
                logger.error(f"Database error storing message and deducting credits: {str(db_error)}")
                db.session.rollback()
        else:
            logger.debug("Skipping message storage and credit deduction - database not available")
        
        # Send response back to user
        send_message(chat_id, llm_response)
        
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        error_message = "Sorry, I encountered an error while processing your request. Please try again later."
        send_message(chat_id, error_message)
