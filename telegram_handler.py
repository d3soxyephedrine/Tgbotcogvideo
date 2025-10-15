import os
import logging
import requests
import threading
from llm_api import generate_response, generate_image
from models import db, User, Message, Payment, Transaction
from datetime import datetime

DEFAULT_MODEL = "openai/gpt-4o"

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

def send_message(chat_id, text, parse_mode=None):
    """Send a message to a specific chat in Telegram
    
    Args:
        chat_id (int): The ID of the chat to send to
        text (str): The text message to send
        parse_mode (str | None): Parse mode for formatting (default: None for plain text, use "Markdown" for formatting)
    
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


def edit_message(chat_id, message_id, text, parse_mode=None):
    """Edit an existing message in Telegram
    
    Args:
        chat_id (int): The ID of the chat
        message_id (int): The ID of the message to edit
        text (str): The new text
        parse_mode (str | None): Parse mode for formatting
    
    Returns:
        dict: The response from Telegram API
    """
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not configured")
        return {"error": "Bot token not configured"}
    
    try:
        # Telegram limits message edits to 4096 characters - truncate if needed
        if len(text) > 4096:
            text = text[:4093] + "..."
        
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
            
        response = requests.post(
            f"{BASE_URL}/editMessageText",
            json=payload
        )
        result = response.json()
        
        # Log errors for debugging (except "message not modified" which is expected)
        if not result.get("ok") and "message is not modified" not in result.get("description", "").lower():
            logger.debug(f"Telegram edit error: {result}")
            
        return result
    except Exception as e:
        logger.debug(f"Error editing message: {str(e)}")
        return {"error": str(e)}

def get_help_message():
    """Get the help message with available commands"""
    help_text = """
🤖 *Uncensored AI Bot Commands* 🤖

/start - Start the bot
/help - Display this help message
/model - Show current model 
/balance - Check your credit balance
/buy - Purchase more credits
/clear - Clear your conversation history
/imagine <prompt> - Generate image (10 credits)

💡 *Pricing:*
• Text message: 1 credit
• Image generation: 10 credits

Send any message to get an uncensored AI response!
Use /imagine to generate images with Grok-2-Image-Gen!
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
                            credits=100
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
                            model_used=os.environ.get('MODEL', DEFAULT_MODEL),
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
                            model_used=os.environ.get('MODEL', DEFAULT_MODEL),
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

• 200 credits = $10.00
• 500 credits = $25.00
• 1000 credits = $50.00

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
                            model_used=os.environ.get('MODEL', DEFAULT_MODEL),
                            credits_charged=0
                        )
                        db.session.add(message_record)
                        db.session.commit()
                except Exception as db_error:
                    logger.error(f"Database error storing buy command: {str(db_error)}")
            
            # Send response without Markdown (URL causes parsing issues)
            send_message(chat_id, response, parse_mode=None)
            return
        
        # Check for /clear command
        if text.lower() == '/clear':
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        # First, delete all transactions that reference messages for this user
                        # Get all message IDs for this user
                        message_ids = [msg.id for msg in Message.query.filter_by(user_id=user_id).all()]
                        
                        # Delete transactions that reference these messages
                        if message_ids:
                            Transaction.query.filter(Transaction.message_id.in_(message_ids)).delete(synchronize_session=False)
                        
                        # Now delete all messages for this user
                        deleted_count = Message.query.filter_by(user_id=user_id).delete()
                        db.session.commit()
                        
                        response = f"✅ Conversation history cleared!\n\n{deleted_count} messages deleted from your history.\n\nYou can now start a fresh conversation with full system prompt effectiveness."
                        logger.info(f"Cleared {deleted_count} messages for user {user_id}")
                except Exception as db_error:
                    logger.error(f"Database error clearing history: {str(db_error)}")
                    db.session.rollback()
                    response = "❌ Error clearing conversation history. Please try again."
            else:
                response = "❌ Conversation history feature requires database access."
            
            # Send response
            send_message(chat_id, response)
            return
            
        # Check for /imagine command (image generation)
        if text.lower().startswith('/imagine '):
            prompt = text[9:].strip()  # Remove '/imagine ' prefix
            
            if not prompt:
                send_message(chat_id, "❌ Please provide a prompt.\n\nExample: /imagine a cat in a tree at sunset")
                return
            
            # Check credit balance (10 credits required)
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        user = User.query.get(user_id)
                        if user.credits < 10:
                            response = f"⚠️ Insufficient credits!\n\nYou have {user.credits} credits but need 10 credits to generate an image.\n\nUse /buy to purchase more credits."
                            send_message(chat_id, response)
                            return
                except Exception as db_error:
                    logger.error(f"Database error checking credits: {str(db_error)}")
            
            # Send initial processing message
            status_msg = send_message(chat_id, "🎨 Generating image with Grok-2-Image-Gen...", parse_mode=None)
            
            # Generate image using Grok-2-Image-Gen
            result = generate_image(prompt)
            
            if result.get("success"):
                image_url = result.get("image_url")
                
                # Download image from URL
                try:
                    img_response = requests.get(image_url, timeout=30)
                    img_response.raise_for_status()
                    
                    # Send image to user
                    photo_payload = {
                        "chat_id": chat_id,
                        "photo": image_url,
                        "caption": f"🎨 {prompt[:200]}" if len(prompt) <= 200 else f"🎨 {prompt[:197]}..."
                    }
                    
                    requests.post(f"{BASE_URL}/sendPhoto", json=photo_payload)
                    
                    # Deduct 10 credits SYNCHRONOUSLY
                    if DB_AVAILABLE and user_id:
                        try:
                            from flask import current_app
                            with current_app.app_context():
                                user = User.query.get(user_id)
                                if user:
                                    user.credits = max(0, user.credits - 10)
                                    db.session.commit()
                                    logger.info(f"Deducted 10 credits for image generation, user {user_id}")
                        except Exception as db_error:
                            logger.error(f"Database error deducting credits: {str(db_error)}")
                            db.session.rollback()
                    
                    # Store in background thread
                    def store_image_record():
                        if DB_AVAILABLE and user_id:
                            try:
                                from flask import current_app
                                with current_app.app_context():
                                    message_record = Message(
                                        user_id=user_id,
                                        user_message=f"/imagine {prompt}",
                                        bot_response=image_url,
                                        model_used="grok-2-image",
                                        credits_charged=10
                                    )
                                    db.session.add(message_record)
                                    db.session.flush()
                                    
                                    transaction = Transaction(
                                        user_id=user_id,
                                        credits_used=10,
                                        message_id=message_record.id,
                                        transaction_type='image_generation',
                                        description=f"Image generation: {prompt[:100]}"
                                    )
                                    db.session.add(transaction)
                                    db.session.commit()
                                    logger.debug(f"Image generation record stored: {message_record.id}")
                            except Exception as db_error:
                                logger.error(f"Error storing image record: {str(db_error)}")
                                db.session.rollback()
                    
                    threading.Thread(target=store_image_record, daemon=True).start()
                    
                except Exception as e:
                    logger.error(f"Error sending image: {str(e)}")
                    send_message(chat_id, f"❌ Error downloading/sending image: {str(e)}")
            else:
                error_msg = result.get("error", "Unknown error")
                send_message(chat_id, f"❌ Image generation failed: {error_msg}")
            
            return
        
        # Check for model info command
        if text.lower().startswith('/model'):
            current_model = os.environ.get('MODEL', DEFAULT_MODEL)
            response = f"Current model: {current_model}\n\nThis bot uses ChatGPT-4o via OpenRouter for all responses."
            
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
        
        # Fetch conversation history for context
        conversation_history = []
        if DB_AVAILABLE and user_id:
            try:
                from flask import current_app
                with current_app.app_context():
                    # Get last 10 messages for this user (5 exchanges)
                    recent_messages = Message.query.filter_by(user_id=user_id).order_by(Message.created_at.desc()).limit(10).all()
                    
                    # Reverse to get chronological order (oldest first)
                    recent_messages.reverse()
                    
                    # Format as conversation history
                    for msg in recent_messages:
                        conversation_history.append({"role": "user", "content": msg.user_message})
                        if msg.bot_response:
                            conversation_history.append({"role": "assistant", "content": msg.bot_response})
                    
                    logger.info(f"Loaded {len(recent_messages)} previous messages for context")
            except Exception as db_error:
                logger.error(f"Error fetching conversation history: {str(db_error)}")
                conversation_history = []
        
        # Generate response from LLM with conversation context using streaming
        current_model = os.environ.get('MODEL', DEFAULT_MODEL)
        
        # Send initial message that will be updated with streaming response
        initial_msg = send_message(chat_id, "⏳ Generating response...", parse_mode=None)
        streaming_message_id = None
        continuation_messages = []  # Track continuation message IDs
        
        if initial_msg and initial_msg.get("ok"):
            streaming_message_id = initial_msg.get("result", {}).get("message_id")
        
        # Create callback for progressive updates with continuation message support
        CHUNK_SIZE = 4000  # Safe limit for Telegram messages (leaving room for cursor)
        
        def update_telegram_message(accumulated_text):
            nonlocal streaming_message_id
            
            if not streaming_message_id:
                return
            
            # Check if we need to send a continuation message
            if len(accumulated_text) > CHUNK_SIZE:
                # Calculate how many chunks we need
                num_chunks = (len(accumulated_text) - 1) // CHUNK_SIZE + 1
                
                # Process each chunk
                for chunk_idx in range(num_chunks):
                    chunk_start = chunk_idx * CHUNK_SIZE
                    chunk_end = min((chunk_idx + 1) * CHUNK_SIZE, len(accumulated_text))
                    chunk_text = accumulated_text[chunk_start:chunk_end]
                    
                    # Determine if this is the last chunk (needs cursor)
                    is_last_chunk = (chunk_idx == num_chunks - 1)
                    display_text = chunk_text + " ▌" if is_last_chunk else chunk_text
                    
                    if chunk_idx == 0:
                        # Update first message
                        edit_message(chat_id, streaming_message_id, display_text, parse_mode=None)
                    else:
                        # Handle continuation message
                        continuation_idx = chunk_idx - 1
                        
                        if continuation_idx < len(continuation_messages):
                            # Update existing continuation message
                            edit_message(chat_id, continuation_messages[continuation_idx], display_text, parse_mode=None)
                        else:
                            # Create new continuation message (without cursor initially)
                            cont_msg = send_message(chat_id, chunk_text, parse_mode=None)
                            if cont_msg and cont_msg.get("ok"):
                                cont_id = cont_msg.get("result", {}).get("message_id")
                                continuation_messages.append(cont_id)
                                # If this is the last chunk, update it with cursor
                                if is_last_chunk:
                                    edit_message(chat_id, cont_id, display_text, parse_mode=None)
            else:
                # Text fits in one message, just update with cursor
                display_text = accumulated_text + " ▌"
                edit_message(chat_id, streaming_message_id, display_text, parse_mode=None)
        
        # Generate response with streaming and progressive updates
        llm_response = generate_response(text, conversation_history, use_streaming=True, update_callback=update_telegram_message)
        
        # Final update with complete response (remove typing indicator and handle continuation)
        if len(llm_response) <= CHUNK_SIZE:
            # Response fits in one message
            if streaming_message_id:
                edit_message(chat_id, streaming_message_id, llm_response, parse_mode=None)
        else:
            # Split response across multiple messages
            chunks = []
            for i in range(0, len(llm_response), CHUNK_SIZE):
                chunks.append(llm_response[i:i + CHUNK_SIZE])
            
            # Update first message
            if streaming_message_id:
                edit_message(chat_id, streaming_message_id, chunks[0], parse_mode=None)
            
            # Send or update continuation messages
            for idx, chunk in enumerate(chunks[1:], start=1):
                if idx - 1 < len(continuation_messages):
                    # Update existing continuation message
                    edit_message(chat_id, continuation_messages[idx - 1], chunk, parse_mode=None)
                else:
                    # Send new continuation message
                    send_message(chat_id, chunk, parse_mode=None)
        
        # CRITICAL: Deduct credits SYNCHRONOUSLY (must happen before response is sent)
        if DB_AVAILABLE and user_id:
            try:
                from flask import current_app
                with current_app.app_context():
                    # Deduct 1 credit from user immediately
                    user = User.query.get(user_id)
                    if user:
                        user.credits = max(0, user.credits - 1)
                    db.session.commit()
                    logger.info(f"Credits deducted synchronously for user {user_id}")
            except Exception as db_error:
                logger.error(f"Database error deducting credits: {str(db_error)}")
                db.session.rollback()
        
        # Store message and transaction in BACKGROUND THREAD (non-blocking)
        def store_message_async():
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
                        logger.debug(f"Message stored asynchronously: {message_record.id}")
                except Exception as db_error:
                    logger.error(f"Async database error storing message: {str(db_error)}")
                    db.session.rollback()
        
        # Start background thread for message storage (non-blocking)
        storage_thread = threading.Thread(target=store_message_async, daemon=True)
        storage_thread.start()
        
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        error_message = "Sorry, I encountered an error while processing your request. Please try again later."
        send_message(chat_id, error_message)
