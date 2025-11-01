import os
import logging
import requests
import threading
from llm_api import generate_response, generate_image, generate_qwen_image, generate_qwen_edit_image, generate_grok_image, generate_hunyuan_image, generate_wan25_video
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

def get_low_credit_warning(total_credits, daily_credits):
    """Generate a warning message when credits are running low
    
    Args:
        total_credits: Total available credits (daily + purchased)
        daily_credits: Daily credits remaining
        
    Returns:
        Warning message or None if no warning needed
    """
    if total_credits == 0:
        return None  # Handled separately
    elif total_credits <= 5:
        if daily_credits > 0:
            return "\n\n⚠️ LOW CREDITS: You have only 5 credits left! Use /daily tomorrow for free credits or /buy to purchase more."
        else:
            return "\n\n⚠️ LOW CREDITS: You have only 5 credits left! Use /daily for free credits or /buy to purchase more."
    elif total_credits <= 10:
        if daily_credits > 0:
            return "\n\n⚠️ Running low on credits! You have 10 or fewer credits remaining. Use /daily tomorrow for free credits or /buy to purchase more."
        else:
            return "\n\n⚠️ Running low on credits! You have 10 or fewer credits remaining. Use /daily for free credits or /buy to purchase more."
    elif total_credits <= 20:
        return "\n\n💡 Heads up: You're getting low on credits (20 or less). Consider using /daily for free credits or /buy to purchase more."
    return None

def deduct_credits(user, amount):
    """Smart credit deduction: use daily credits first (check expiry), then purchased credits
    
    Args:
        user: User object from database
        amount: Number of credits to deduct
    
    Returns:
        tuple: (success: bool, daily_used: int, purchased_used: int, warning: str or None)
    """
    from datetime import timedelta
    
    now = datetime.utcnow()
    daily_used = 0
    purchased_used = 0
    
    # Check if daily credits are expired
    if user.daily_credits_expiry and now > user.daily_credits_expiry:
        logger.debug(f"Daily credits expired for user {user.telegram_id}, clearing {user.daily_credits} daily credits")
        user.daily_credits = 0
        user.daily_credits_expiry = None
    
    # Calculate total available credits
    total_available = user.daily_credits + user.credits
    
    if total_available < amount:
        logger.debug(f"Insufficient credits: need {amount}, have {total_available} (daily: {user.daily_credits}, purchased: {user.credits})")
        return False, 0, 0, None
    
    # Deduct from daily credits first
    if user.daily_credits > 0:
        daily_deduction = min(user.daily_credits, amount)
        user.daily_credits -= daily_deduction
        daily_used = daily_deduction
        amount -= daily_deduction
        logger.debug(f"Deducted {daily_deduction} from daily credits. Remaining daily: {user.daily_credits}")
    
    # Deduct remaining from purchased credits
    if amount > 0:
        user.credits -= amount
        purchased_used = amount
        logger.debug(f"Deducted {amount} from purchased credits. Remaining purchased: {user.credits}")
    
    # Calculate remaining credits and generate warning if needed
    remaining_total = user.daily_credits + user.credits
    warning = get_low_credit_warning(remaining_total, user.daily_credits)
    
    return True, daily_used, purchased_used, warning

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
        # Telegram limits message edits to 4096 characters - return error if exceeded
        if len(text) > 4096:
            logger.warning(f"Cannot edit message: text length {len(text)} exceeds Telegram limit of 4096")
            return {"ok": False, "error": "Message too long for edit", "length": len(text)}
        
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

def get_photo_url(file_id, max_size_mb=10):
    """Get a publicly accessible URL for a photo from Telegram
    
    Args:
        file_id (str): The file_id from Telegram photo message
        max_size_mb (int): Maximum file size in MB (default: 10MB)
        
    Returns:
        tuple: (photo_url, error_message) - photo_url is None if failed/too large
    """
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not configured")
        return None, "Bot configuration error"
    
    try:
        # Step 1: Get file path and size
        response = requests.get(f"{BASE_URL}/getFile?file_id={file_id}", timeout=10)
        result = response.json()
        
        if not result.get("ok"):
            logger.error(f"Failed to get file path: {result}")
            return None, "Failed to retrieve photo from Telegram"
        
        file_info = result.get("result", {})
        file_path = file_info.get("file_path")
        file_size = file_info.get("file_size", 0)
        
        if not file_path:
            logger.error("No file_path in response")
            return None, "Invalid photo file"
        
        # Step 2: Check file size (convert bytes to MB)
        file_size_mb = file_size / (1024 * 1024)
        logger.info(f"Photo file size: {file_size_mb:.2f} MB")
        
        if file_size_mb > max_size_mb:
            logger.warning(f"Photo too large: {file_size_mb:.2f} MB (max: {max_size_mb} MB)")
            return None, f"❌ Photo too large ({file_size_mb:.1f} MB). Maximum size: {max_size_mb} MB\n\nPlease compress the image or use a smaller photo."
        
        # Step 3: Construct download URL
        photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        logger.info(f"Photo URL obtained: {photo_url} ({file_size_mb:.2f} MB)")
        return photo_url, None
        
    except Exception as e:
        logger.error(f"Error getting photo URL: {str(e)}")
        return None, f"Error retrieving photo: {str(e)}"

def get_help_message():
    """Get the help message with available commands"""
    help_text = """
🤖 *Uncensored AI Bot Commands* 🤖

/start - Start the bot
/help - Display this help message
/daily - Claim 25 free credits (once per 24h, expires in 48h)
/model - Show current model 
/balance - Check your credit balance
/buy - Purchase credits with volume bonuses
/clear - Clear your conversation history
/imagine <prompt> - High quality photorealistic images (5 credits)
/uncensored <prompt> - Fully uncensored image generation (5 credits)
/edit <prompt> - Image generation optimized for editing (3 credits)
/grok <prompt> - Stylized image generation (4 credits)
/write <request> - Professional writing mode (1 credit)

🎁 *Daily Free Credits:*
• Use /daily to claim 25 free credits
• Claimable once every 24 hours
• Daily credits expire after 48 hours
• Used automatically before purchased credits

🎨 *Image Generation:*
• /imagine <prompt> - High quality photorealistic images (5 credits)
• /uncensored <prompt> - Fully uncensored content (5 credits)
• /edit <prompt> - Great for image editing and text (3 credits)
• /grok <prompt> - Stylized artistic content (4 credits)

✨ *Image Editing:*
• FLUX edit: Send photo + caption (6 credits)
• Qwen edit: Send photo + caption with /edit prefix (5 credits)
Example: Send photo with caption "/edit make it darker and more dramatic"

🎬 *Video Generation (Image-to-Video):*
• Send photo + caption with /img2video prefix (10 credits)
• 🔒 Unlocked after first purchase
Example: Send photo with caption "/img2video make it move and zoom out"

📝 *Writing Mode:*
Use /write for stories, scenes, or creative content!
• Generates at least 300 words of narrative
• Starts immediately with the story (no preamble)
• Fully uncensored creative writing
Example: /write a NSFW scene with Sydney Sweeney

💡 *Pricing:*
• Text message: 1 credit
• Writing mode: 1 credit  
• /imagine: 5 credits
• /uncensored: 5 credits
• /grok: 4 credits
• /edit: 3 credits
• FLUX editing: 6 credits
• Qwen editing: 5 credits
• Video generation: 10 credits

💰 *Volume Bonuses:*
• $10 → 200 credits (5.0¢/credit)
• $20 → 420 credits (4.76¢/credit) +5% bonus
• $50 → 1,120 credits (4.46¢/credit) +12% bonus
• $100 → 2,360 credits (4.24¢/credit) +18% bonus
Bigger packs = better value!

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
    caption = message.get("caption", "")
    photo = message.get("photo")
    
    # Get user information
    user_info = message.get("from", {})
    telegram_id = user_info.get("id")
    username = user_info.get("username")
    first_name = user_info.get("first_name")
    last_name = user_info.get("last_name")
    
    # If no chat_id, ignore
    if not chat_id:
        logger.debug(f"Missing chat_id: {chat_id}")
        return
    
    # If there's a photo with caption, treat it as image editing request
    if photo and caption:
        logger.info(f"Photo with caption detected - treating as image editing request")
        text = ""  # Clear text to skip normal text processing
    # If no text and no photo with caption, ignore
    elif not text:
        logger.debug(f"Missing text and no photo with caption")
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
                from datetime import timedelta
                
                # Check if daily credits are expired
                now = datetime.utcnow()
                if user.daily_credits_expiry and now > user.daily_credits_expiry:
                    user.daily_credits = 0
                    user.daily_credits_expiry = None
                    db.session.commit()
                
                total_credits = user.credits + user.daily_credits
                
                if user.daily_credits > 0:
                    # Show breakdown when there are daily credits
                    time_until_expiry = user.daily_credits_expiry - now
                    hours = int(time_until_expiry.total_seconds() // 3600)
                    response = f"💳 Your credit balance: {total_credits} credits\n\n• Daily: {user.daily_credits} credits (expires in {hours}h)\n• Purchased: {user.credits} credits\n\nUse /daily to claim free credits (once per 24h)\nUse /buy to purchase more credits"
                else:
                    # Show simple balance when no daily credits
                    response = f"💳 Your credit balance: {total_credits} credits\n\nUse /daily to claim free credits (once per 24h)\nUse /buy to purchase more credits"
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
        
        # Check for /daily command
        if text.lower() == '/daily':
            if DB_AVAILABLE and user:
                try:
                    from flask import current_app
                    from datetime import timedelta
                    
                    with current_app.app_context():
                        # Reload user in this context to avoid detached object issues
                        user = User.query.filter_by(telegram_id=telegram_id).first()
                        if not user:
                            send_message(chat_id, "❌ User not found. Please try again.")
                            return
                        
                        now = datetime.utcnow()
                        
                        # Check if user can claim (24h cooldown)
                        if user.last_daily_claim_at:
                            time_since_last_claim = now - user.last_daily_claim_at
                            if time_since_last_claim < timedelta(hours=24):
                                # Calculate time until next claim
                                time_until_next = timedelta(hours=24) - time_since_last_claim
                                hours = int(time_until_next.total_seconds() // 3600)
                                minutes = int((time_until_next.total_seconds() % 3600) // 60)
                                response = f"⏰ Daily credits already claimed!\n\nYou can claim again in {hours}h {minutes}m."
                                send_message(chat_id, response)
                                return
                        
                        # Grant 25 daily credits with 48h expiry
                        user.daily_credits = 25
                        user.daily_credits_expiry = now + timedelta(hours=48)
                        user.last_daily_claim_at = now
                        db.session.commit()
                        
                        # Calculate expiry countdown
                        expiry_time = user.daily_credits_expiry
                        time_until_expiry = expiry_time - now
                        hours = int(time_until_expiry.total_seconds() // 3600)
                        
                        response = f"🎁 Daily credits claimed!\n\n+25 credits added (expires in {hours}h)\n\n💳 Total balance: {user.credits + user.daily_credits} credits\n  • Daily: {user.daily_credits} credits\n  • Purchased: {user.credits} credits\n\nClaim again in 24h!"
                        
                        logger.info(f"User {telegram_id} claimed daily credits: +25 credits")
                except Exception as db_error:
                    logger.error(f"Database error processing /daily: {str(db_error)}")
                    db.session.rollback()
                    response = "❌ Error processing daily claim. Please try again."
            else:
                response = "💳 Daily credits require database access."
            
            # Send response
            send_message(chat_id, response)
            return
        
        # Check for /buy command
        if text.lower() == '/buy':
            # Get domain from environment variables
            domain = os.environ.get('REPLIT_DOMAINS', '').split(',')[0] if os.environ.get('REPLIT_DOMAINS') else os.environ.get('REPLIT_DEV_DOMAIN') or 'your-app.replit.app'
            
            response = f"""💰 Credit Packages (Volume Bonuses!)

• $10 → 200 credits (5.0¢/credit)
• $20 → 420 credits (4.76¢/credit) +5% bonus
• $50 → 1,120 credits (4.46¢/credit) +12% bonus  
• $100 → 2,360 credits (4.24¢/credit) +18% bonus

To purchase credits, visit:
https://{domain}/buy?telegram_id={telegram_id}

Bigger packs = better value!
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
            
            # OPTIMIZATION: Check balance and deduct credits upfront (before generation)
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        user = User.query.get(user_id)
                        if not user:
                            logger.error(f"User not found for image generation: {user_id}")
                            send_message(chat_id, "❌ User account not found. Please try /start first.")
                            return
                        
                        # Deduct 5 credits immediately (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, 5)
                        if not success:
                            total = user.credits + user.daily_credits
                            response = f"⚠️ Insufficient credits!\n\nYou have {total} credits but need 5 credits to generate an image.\n\nUse /buy to purchase more credits or /daily to claim free credits."
                            send_message(chat_id, response)
                            return
                        
                        db.session.commit()
                        logger.debug(f"5 credits deducted for image (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
                        
                        # Send credit warning if needed
                        if credit_warning:
                            send_message(chat_id, credit_warning)
                except Exception as db_error:
                    logger.error(f"Database error checking/deducting credits: {str(db_error)}")
            
            # Send initial processing message
            status_msg = send_message(chat_id, "🎨 Generating your image...", parse_mode=None)
            
            # Generate image using Novita AI with SDXL
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
                    
                    # CRITICAL: Store message AND transaction SYNCHRONOUSLY for reliability
                    # Credit already deducted above, so user can't use same credits twice
                    if DB_AVAILABLE and user_id:
                        try:
                            from flask import current_app
                            with current_app.app_context():
                                # Create message record immediately for conversation history
                                message_record = Message(
                                    user_id=user_id,
                                    user_message=f"/imagine {prompt}",
                                    bot_response=image_url,
                                    model_used="flux-1-kontext-max",
                                    credits_charged=5
                                )
                                db.session.add(message_record)
                                db.session.commit()
                                message_id = message_record.id
                                logger.info(f"Image message stored synchronously for user {user_id}: {message_id}")
                                
                                # Also store transaction synchronously for reliability
                                transaction = Transaction(
                                    user_id=user_id,
                                    credits_used=5,
                                    message_id=message_id,
                                    transaction_type='image_generation',
                                    description=f"Image generation: {prompt[:100]}"
                                )
                                db.session.add(transaction)
                                db.session.commit()
                                logger.debug(f"Image transaction stored synchronously: message_id={message_id}")
                        except Exception as db_error:
                            logger.error(f"Database error storing image message/transaction: {str(db_error)}")
                            # Flask-SQLAlchemy automatically rolls back on exception within app context
                    
                except Exception as e:
                    logger.error(f"Error sending image: {str(e)}")
                    send_message(chat_id, f"❌ Error downloading/sending image: {str(e)}")
            else:
                error_msg = result.get("error", "Unknown error")
                
                # Refund credits since generation failed
                if DB_AVAILABLE and user_id:
                    try:
                        from flask import current_app
                        with current_app.app_context():
                            user = User.query.get(user_id)
                            if user:
                                user.credits += 5
                                db.session.commit()
                                logger.info(f"Refunded 5 credits due to failed FLUX generation. New balance: {user.credits}")
                    except Exception as db_error:
                        logger.error(f"Database error refunding credits: {str(db_error)}")
                
                send_message(chat_id, f"❌ Image generation failed: {error_msg}\n\n✅ 5 credits have been refunded to your account.")
            
            return
        
        # Check for /edit command (Qwen-Image generation - great for image editing and text)
        if text.lower().startswith('/edit '):
            prompt = text[6:].strip()  # Remove '/edit ' prefix
            
            if not prompt:
                send_message(chat_id, "❌ Please provide a prompt.\n\nExample: /edit a cyberpunk poster with 'NEON CITY' text")
                return
            
            # OPTIMIZATION: Check balance and deduct credits upfront (before generation)
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        user = User.query.get(user_id)
                        if not user:
                            logger.error(f"User not found for Qwen image generation: {user_id}")
                            send_message(chat_id, "❌ User account not found. Please try /start first.")
                            return
                        
                        # Deduct 3 credits immediately (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, 3)
                        if not success:
                            total = user.credits + user.daily_credits
                            response = f"⚠️ Insufficient credits!\n\nYou have {total} credits but need 3 credits to generate a Qwen image.\n\nUse /buy to purchase more credits or /daily to claim free credits."
                            send_message(chat_id, response)
                            return
                        
                        db.session.commit()
                        logger.debug(f"3 credits deducted for Qwen image (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
                        
                        # Send credit warning if needed
                        if credit_warning:
                            send_message(chat_id, credit_warning)
                except Exception as db_error:
                    logger.error(f"Database error checking/deducting credits: {str(db_error)}")
            
            # Send initial processing message
            status_msg = send_message(chat_id, "🎨 Generating Qwen image (less censored)...", parse_mode=None)
            
            # Generate image using Novita AI Qwen-Image
            result = generate_qwen_image(prompt)
            
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
                        "caption": f"🖼️ {prompt[:200]}" if len(prompt) <= 200 else f"🖼️ {prompt[:197]}..."
                    }
                    
                    requests.post(f"{BASE_URL}/sendPhoto", json=photo_payload)
                    
                    # CRITICAL: Store message AND transaction SYNCHRONOUSLY for reliability
                    # Credit already deducted above, so user can't use same credits twice
                    if DB_AVAILABLE and user_id:
                        try:
                            from flask import current_app
                            with current_app.app_context():
                                # Create message record immediately for conversation history
                                message_record = Message(
                                    user_id=user_id,
                                    user_message=f"/qwen {prompt}",
                                    bot_response=image_url,
                                    model_used="qwen-image",
                                    credits_charged=3
                                )
                                db.session.add(message_record)
                                db.session.commit()
                                message_id = message_record.id
                                logger.info(f"Qwen image message stored synchronously for user {user_id}: {message_id}")
                                
                                # Also store transaction synchronously for reliability
                                transaction = Transaction(
                                    user_id=user_id,
                                    credits_used=3,
                                    message_id=message_id,
                                    transaction_type='qwen_image_generation',
                                    description=f"Qwen image generation: {prompt[:100]}"
                                )
                                db.session.add(transaction)
                                db.session.commit()
                                logger.debug(f"Qwen image transaction stored synchronously: message_id={message_id}")
                        except Exception as db_error:
                            logger.error(f"Database error storing Qwen image message/transaction: {str(db_error)}")
                            # Flask-SQLAlchemy automatically rolls back on exception within app context
                    
                except Exception as e:
                    logger.error(f"Error sending Qwen image: {str(e)}")
                    send_message(chat_id, f"❌ Error downloading/sending image: {str(e)}")
            else:
                error_msg = result.get("error", "Unknown error")
                
                # Refund credits since generation failed
                if DB_AVAILABLE and user_id:
                    try:
                        from flask import current_app
                        with current_app.app_context():
                            user = User.query.get(user_id)
                            if user:
                                user.credits += 3
                                db.session.commit()
                                logger.info(f"Refunded 3 credits due to failed Qwen generation. New balance: {user.credits}")
                    except Exception as db_error:
                        logger.error(f"Database error refunding credits: {str(db_error)}")
                
                send_message(chat_id, f"❌ Qwen image generation failed: {error_msg}\n\n✅ 3 credits have been refunded to your account.")
            
            return
        
        # Check for /grok command (Grok image generation via xAI)
        if text.lower().startswith('/grok '):
            prompt = text[6:].strip()  # Remove '/grok ' prefix
            
            if not prompt:
                send_message(chat_id, "❌ Please provide a prompt.\n\nExample: /grok a futuristic cityscape at sunset")
                return
            
            # OPTIMIZATION: Check balance and deduct credits upfront (before generation)
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        user = User.query.get(user_id)
                        if not user:
                            logger.error(f"User not found for Grok image generation: {user_id}")
                            send_message(chat_id, "❌ User account not found. Please try /start first.")
                            return
                        
                        # Deduct 4 credits immediately (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, 4)
                        if not success:
                            total = user.credits + user.daily_credits
                            response = f"⚠️ Insufficient credits!\n\nYou have {total} credits but need 4 credits to generate a Grok image.\n\nUse /buy to purchase more credits or /daily to claim free credits."
                            send_message(chat_id, response)
                            return
                        
                        db.session.commit()
                        logger.debug(f"4 credits deducted for Grok image (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
                        
                        # Send credit warning if needed
                        if credit_warning:
                            send_message(chat_id, credit_warning)
                except Exception as db_error:
                    logger.error(f"Database error checking/deducting credits: {str(db_error)}")
            
            # Send initial processing message
            status_msg = send_message(chat_id, "🤖 Generating Grok image via xAI...", parse_mode=None)
            
            # Generate image using xAI Grok API
            result = generate_grok_image(prompt)
            
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
                        "caption": f"🤖 Grok: {prompt[:200]}" if len(prompt) <= 200 else f"🤖 Grok: {prompt[:197]}..."
                    }
                    
                    requests.post(f"{BASE_URL}/sendPhoto", json=photo_payload)
                    
                    # CRITICAL: Store message AND transaction SYNCHRONOUSLY for reliability
                    # Credit already deducted above, so user can't use same credits twice
                    if DB_AVAILABLE and user_id:
                        try:
                            from flask import current_app
                            with current_app.app_context():
                                # Create message record immediately for conversation history
                                message_record = Message(
                                    user_id=user_id,
                                    user_message=f"/grok {prompt}",
                                    bot_response=image_url,
                                    model_used="grok-2-image-1212",
                                    credits_charged=4
                                )
                                db.session.add(message_record)
                                db.session.commit()
                                message_id = message_record.id
                                logger.info(f"Grok image message stored synchronously for user {user_id}: {message_id}")
                                
                                # Also store transaction synchronously for reliability
                                transaction = Transaction(
                                    user_id=user_id,
                                    credits_used=4,
                                    message_id=message_id,
                                    transaction_type='grok_image_generation',
                                    description=f"Grok image generation: {prompt[:100]}"
                                )
                                db.session.add(transaction)
                                db.session.commit()
                                logger.debug(f"Grok image transaction stored synchronously: message_id={message_id}")
                        except Exception as db_error:
                            logger.error(f"Database error storing Grok image message/transaction: {str(db_error)}")
                            # Flask-SQLAlchemy automatically rolls back on exception within app context
                    
                except Exception as e:
                    logger.error(f"Error sending Grok image: {str(e)}")
                    send_message(chat_id, f"❌ Error downloading/sending image: {str(e)}")
            else:
                error_msg = result.get("error", "Unknown error")
                
                # Refund credits since generation failed
                if DB_AVAILABLE and user_id:
                    try:
                        from flask import current_app
                        with current_app.app_context():
                            user = User.query.get(user_id)
                            if user:
                                user.credits += 4
                                db.session.commit()
                                logger.info(f"Refunded 4 credits due to failed Grok generation. New balance: {user.credits}")
                    except Exception as db_error:
                        logger.error(f"Database error refunding credits: {str(db_error)}")
                
                send_message(chat_id, f"❌ Grok image generation failed: {error_msg}\n\n✅ 4 credits have been refunded to your account.")
            
            return
        
        # Check for /uncensored command (Hunyuan-Image-3 generation via Novita AI - fully uncensored)
        if text.lower().startswith('/uncensored '):
            prompt = text[12:].strip()  # Remove '/uncensored ' prefix
            
            if not prompt:
                send_message(chat_id, "❌ Please provide a prompt.\n\nExample: /uncensored a beautiful landscape with mountains")
                return
            
            # OPTIMIZATION: Check balance and deduct credits upfront (before generation)
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        user = User.query.get(user_id)
                        if not user:
                            logger.error(f"User not found for Hunyuan image generation: {user_id}")
                            send_message(chat_id, "❌ User account not found. Please try /start first.")
                            return
                        
                        # Deduct 5 credits immediately (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, 5)
                        if not success:
                            total = user.credits + user.daily_credits
                            response = f"⚠️ Insufficient credits!\n\nYou have {total} credits but need 5 credits to generate an uncensored image.\n\nUse /buy to purchase more credits or /daily to claim free credits."
                            send_message(chat_id, response)
                            return
                        
                        db.session.commit()
                        logger.debug(f"5 credits deducted for Hunyuan image (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
                        
                        # Send credit warning if needed
                        if credit_warning:
                            send_message(chat_id, credit_warning)
                except Exception as db_error:
                    logger.error(f"Database error checking/deducting credits: {str(db_error)}")
            
            # Send initial processing message
            status_msg = send_message(chat_id, "🎨 Generating uncensored image...", parse_mode=None)
            
            # Generate image using Novita AI Hunyuan-Image-3
            result = generate_hunyuan_image(prompt)
            
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
                        "caption": f"🎨 Hunyuan: {prompt[:200]}" if len(prompt) <= 200 else f"🎨 Hunyuan: {prompt[:197]}..."
                    }
                    
                    requests.post(f"{BASE_URL}/sendPhoto", json=photo_payload)
                    
                    # CRITICAL: Store message AND transaction SYNCHRONOUSLY for reliability
                    # Credit already deducted above, so user can't use same credits twice
                    if DB_AVAILABLE and user_id:
                        try:
                            from flask import current_app
                            with current_app.app_context():
                                # Create message record immediately for conversation history
                                message_record = Message(
                                    user_id=user_id,
                                    user_message=f"/hunyuan {prompt}",
                                    bot_response=image_url,
                                    model_used="hunyuan-image-3",
                                    credits_charged=5
                                )
                                db.session.add(message_record)
                                db.session.commit()
                                message_id = message_record.id
                                logger.info(f"Hunyuan image message stored synchronously for user {user_id}: {message_id}")
                                
                                # Also store transaction synchronously for reliability
                                transaction = Transaction(
                                    user_id=user_id,
                                    credits_used=5,
                                    message_id=message_id,
                                    transaction_type='hunyuan_image_generation',
                                    description=f"Hunyuan image generation: {prompt[:100]}"
                                )
                                db.session.add(transaction)
                                db.session.commit()
                                logger.debug(f"Hunyuan image transaction stored synchronously: message_id={message_id}")
                        except Exception as db_error:
                            logger.error(f"Database error storing Hunyuan image message/transaction: {str(db_error)}")
                            # Flask-SQLAlchemy automatically rolls back on exception within app context
                    
                except Exception as e:
                    logger.error(f"Error sending Hunyuan image: {str(e)}")
                    send_message(chat_id, f"❌ Error downloading/sending image: {str(e)}")
            else:
                error_msg = result.get("error", "Unknown error")
                
                # Refund credits since generation failed
                if DB_AVAILABLE and user_id:
                    try:
                        from flask import current_app
                        with current_app.app_context():
                            user = User.query.get(user_id)
                            if user:
                                user.credits += 5
                                db.session.commit()
                                logger.info(f"Refunded 5 credits due to failed Hunyuan generation. New balance: {user.credits}")
                    except Exception as db_error:
                        logger.error(f"Database error refunding credits: {str(db_error)}")
                
                send_message(chat_id, f"❌ Hunyuan image generation failed: {error_msg}\n\n✅ 5 credits have been refunded to your account.")
            
            return
        
        # Check for /img2video command (WAN 2.5 video generation)
        if photo and caption and caption.lower().startswith('/img2video'):
            prompt = caption[11:].strip()  # Remove '/img2video ' prefix (optional prompt)
            
            logger.info(f"Processing video generation request with prompt: {prompt[:50] if prompt else 'No prompt'}...")
            
            # OPTIMIZATION: Check balance and deduct credits upfront (before video generation)
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        user = User.query.get(user_id)
                        if not user:
                            logger.error(f"User not found for video generation: {user_id}")
                            send_message(chat_id, "❌ User account not found. Please try /start first.")
                            return
                        
                        # VIDEO PAYWALL: Check if user has ever purchased
                        if not user.last_purchase_at:
                            response = "🔒 Video generation is locked!\n\nTo unlock video generation, make your first purchase.\n\nUse /buy to get started with credits."
                            send_message(chat_id, response)
                            return
                        
                        # Deduct 10 credits immediately (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, 10)
                        if not success:
                            total = user.credits + user.daily_credits
                            response = f"⚠️ Insufficient credits!\n\nYou have {total} credits but need 10 credits to generate a video.\n\nUse /buy to purchase more credits or /daily to claim free credits."
                            send_message(chat_id, response)
                            return
                        
                        db.session.commit()
                        logger.debug(f"10 credits deducted for video generation (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
                        
                        # Send credit warning if needed
                        if credit_warning:
                            send_message(chat_id, credit_warning)
                except Exception as db_error:
                    logger.error(f"Database error checking/deducting credits: {str(db_error)}")
            
            # Download the image first
            try:
                photo_file = photo[-1]  # Get largest photo
                file_id = photo_file.get("file_id")
                
                # Get file info
                file_info_response = requests.get(f"{BASE_URL}/getFile?file_id={file_id}")
                file_info = file_info_response.json()
                
                if not file_info.get("ok"):
                    send_message(chat_id, "❌ Failed to get image file information")
                    return
                
                file_path = file_info.get("result", {}).get("file_path")
                if not file_path:
                    send_message(chat_id, "❌ Failed to get image file path")
                    return
                
                image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
                
                # Generate video in background thread to avoid webhook timeout
                from flask import current_app
                app = current_app._get_current_object()
                
                def generate_video_background():
                    with app.app_context():
                        send_message(chat_id, "🎬 Generating video from your image... This may take up to 2 minutes.")
                        
                        result = generate_wan25_video(image_url, prompt)
                        
                        if result.get("success"):
                            video_url = result.get("video_url")
                            try:
                                send_message(chat_id, f"✨ Video generated successfully!\n\n{video_url}")
                                
                                # Store message and transaction synchronously
                                if DB_AVAILABLE and user_id:
                                    try:
                                        message_id = store_message(user_id, f"Video from image: {prompt[:100] if prompt else 'No prompt'}", f"Video: {video_url}", credits_cost=10)
                                        
                                        transaction = Transaction(
                                            user_id=user_id,
                                            credits_used=10,
                                            message_id=message_id,
                                            transaction_type='video_generation',
                                            description=f"Video: {prompt[:100] if prompt else 'No prompt'}"
                                        )
                                        db.session.add(transaction)
                                        db.session.commit()
                                        logger.debug(f"Video transaction stored: message_id={message_id}")
                                    except Exception as db_error:
                                        logger.error(f"Database error storing video message/transaction: {str(db_error)}")
                                
                            except Exception as e:
                                logger.error(f"Error sending video: {str(e)}")
                                send_message(chat_id, f"❌ Error sending video: {str(e)}")
                        else:
                            error_msg = result.get("error", "Unknown error")
                            
                            # Refund credits since generation failed
                            if DB_AVAILABLE and user_id:
                                try:
                                    user = User.query.get(user_id)
                                    if user:
                                        user.credits += 10
                                        db.session.commit()
                                        logger.info(f"Refunded 10 credits due to failed video generation. New balance: {user.credits}")
                                except Exception as db_error:
                                    logger.error(f"Database error refunding credits: {str(db_error)}")
                            
                            send_message(chat_id, f"❌ Video generation failed: {error_msg}\n\n✅ 10 credits have been refunded to your account.")
                
                # Start background thread
                thread = threading.Thread(target=generate_video_background)
                thread.start()
                
            except Exception as e:
                logger.error(f"Error processing video generation request: {str(e)}")
                send_message(chat_id, f"❌ Error: {str(e)}")
            
            return
        
        # Check for photo with caption (image editing)
        if photo and caption:
            # Detect which model to use based on caption prefix
            use_qwen = caption.lower().startswith('/edit ')
            
            if use_qwen:
                # Remove /edit prefix for actual prompt
                edit_prompt = caption[6:].strip()
                credits_required = 5
                model_name = "qwen-image-edit"
                status_message = "🎨 Editing with Qwen..."
            else:
                edit_prompt = caption
                credits_required = 6
                model_name = "flux-1-kontext-max-edit"
                status_message = "🎨 Editing with FLUX..."
            
            logger.info(f"Processing {model_name} image editing request: {edit_prompt[:50]}...")
            
            # OPTIMIZATION: Check balance and deduct credits upfront (before editing)
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        user = User.query.get(user_id)
                        if not user:
                            logger.error(f"User not found for image editing: {user_id}")
                            send_message(chat_id, "❌ User account not found. Please try /start first.")
                            return
                        
                        # Deduct credits immediately (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, credits_required)
                        if not success:
                            total = user.credits + user.daily_credits
                            model_display = "Qwen" if use_qwen else "FLUX"
                            response = f"⚠️ Insufficient credits!\n\nYou have {total} credits but need {credits_required} credits to edit with {model_display}.\n\nUse /buy to purchase more credits or /daily to claim free credits."
                            send_message(chat_id, response)
                            return
                        
                        db.session.commit()
                        logger.debug(f"{credits_required} credits deducted for {model_name} editing (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
                        
                        # Send credit warning if needed
                        if credit_warning:
                            send_message(chat_id, credit_warning)
                except Exception as db_error:
                    logger.error(f"Database error checking/deducting credits: {str(db_error)}")
            
            # Send initial processing message
            status_msg = send_message(chat_id, status_message, parse_mode=None)
            
            # Get highest quality photo (last element in array)
            file_id = photo[-1].get("file_id")
            if not file_id:
                send_message(chat_id, "❌ Could not get photo file ID")
                return
            
            # Capture Flask app object for use in background thread (current_app doesn't work in threads)
            flask_app = None
            if DB_AVAILABLE:
                from flask import current_app
                flask_app = current_app._get_current_object()
            
            # Process image editing in background thread to avoid webhook timeout (Telegram has 60s limit)
            def process_image_edit_background():
                """Background function to process image editing without blocking webhook"""
                try:
                    # Get publicly accessible URL for the photo (in background to avoid webhook timeout)
                    photo_url, photo_error = get_photo_url(file_id)
                    if not photo_url:
                        # Send user-friendly error message (includes size limit info if applicable)
                        error_msg = photo_error if photo_error else "❌ Could not download photo from Telegram"
                        send_message(chat_id, error_msg)
                        # Refund credits
                        if DB_AVAILABLE and user_id and flask_app:
                            try:
                                with flask_app.app_context():
                                    user = User.query.get(user_id)
                                    if user:
                                        user.credits += credits_required
                                        db.session.commit()
                                        logger.info(f"Refunded {credits_required} credits due to photo download failure. New balance: {user.credits}")
                            except Exception as db_error:
                                logger.error(f"Database error refunding credits: {str(db_error)}")
                        return
                    
                    logger.info(f"Photo URL: {photo_url}")
                    
                    # Call appropriate editing function based on model choice
                    if use_qwen:
                        result = generate_qwen_edit_image(photo_url, edit_prompt)
                    else:
                        result = generate_image(edit_prompt, image_url=photo_url)
                    
                    if result.get("success"):
                        image_url = result.get("image_url")
                        
                        # Download image from URL
                        try:
                            img_response = requests.get(image_url, timeout=30)
                            img_response.raise_for_status()
                            
                            # Send edited image to user
                            photo_payload = {
                                "chat_id": chat_id,
                                "photo": image_url,
                                "caption": f"✨ Edited: {edit_prompt[:180]}" if len(edit_prompt) <= 180 else f"✨ Edited: {edit_prompt[:177]}..."
                            }
                            
                            requests.post(f"{BASE_URL}/sendPhoto", json=photo_payload)
                            
                            # CRITICAL: Store message AND transaction SYNCHRONOUSLY for reliability
                            # Credit already deducted above, so user can't use same credits twice
                            if DB_AVAILABLE and user_id and flask_app:
                                try:
                                    with flask_app.app_context():
                                        # Create message record immediately for conversation history
                                        message_record = Message(
                                            user_id=user_id,
                                            user_message=f"[Image Edit] {caption}",
                                            bot_response=image_url,
                                            model_used=model_name,
                                            credits_charged=credits_required
                                        )
                                        db.session.add(message_record)
                                        db.session.commit()
                                        message_id = message_record.id
                                        logger.info(f"Image edit message stored synchronously for user {user_id}: {message_id}")
                                        
                                        # Also store transaction synchronously for reliability
                                        transaction_type = 'qwen_image_editing' if use_qwen else 'image_editing'
                                        transaction = Transaction(
                                            user_id=user_id,
                                            credits_used=credits_required,
                                            message_id=message_id,
                                            transaction_type=transaction_type,
                                            description=f"{model_name}: {edit_prompt[:100]}"
                                        )
                                        db.session.add(transaction)
                                        db.session.commit()
                                        logger.debug(f"Image edit transaction stored synchronously: message_id={message_id}")
                                except Exception as db_error:
                                    logger.error(f"Database error storing image edit message/transaction: {str(db_error)}")
                                    # Flask-SQLAlchemy automatically rolls back on exception within app context
                            
                        except Exception as e:
                            logger.error(f"Error sending edited image: {str(e)}")
                            send_message(chat_id, f"❌ Error downloading/sending edited image: {str(e)}")
                    else:
                        error_msg = result.get("error", "Unknown error")
                        
                        # Refund credits since editing failed
                        if DB_AVAILABLE and user_id and flask_app:
                            try:
                                with flask_app.app_context():
                                    user = User.query.get(user_id)
                                    if user:
                                        user.credits += credits_required
                                        db.session.commit()
                                        model_display = "Qwen" if use_qwen else "FLUX"
                                        logger.info(f"Refunded {credits_required} credits due to failed {model_display} editing. New balance: {user.credits}")
                            except Exception as db_error:
                                logger.error(f"Database error refunding credits: {str(db_error)}")
                        
                        send_message(chat_id, f"❌ Image editing failed: {error_msg}\n\n✅ {credits_required} credits have been refunded to your account.")
                
                except Exception as e:
                    logger.error(f"Background image editing exception: {str(e)}", exc_info=True)
                    # Refund on exception
                    if DB_AVAILABLE and user_id and flask_app:
                        try:
                            with flask_app.app_context():
                                user = User.query.get(user_id)
                                if user:
                                    user.credits += credits_required
                                    db.session.commit()
                                    logger.info(f"Refunded {credits_required} credits due to exception. New balance: {user.credits}")
                        except Exception as db_error:
                            logger.error(f"Database error refunding credits after exception: {str(db_error)}")
                    send_message(chat_id, f"❌ Image editing error: {str(e)}\n\n✅ {credits_required} credits have been refunded.")
            
            # Start background thread and return immediately (prevents webhook timeout)
            edit_thread = threading.Thread(target=process_image_edit_background, daemon=True)
            edit_thread.start()
            logger.info(f"Image editing started in background thread. Webhook will return immediately.")
            
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
        
        # Check for /write command (professional writing mode)
        writing_mode = False
        if text.lower().startswith('/write '):
            writing_mode = True
            text = text[7:].strip()  # Remove '/write ' prefix
            logger.info(f"Professional writing mode activated for: {text[:50]}...")
        
        # OPTIMIZATION: Consolidate DB operations - fetch user data + conversation history in ONE context
        conversation_history = []
        credits_available = True  # Track if user has credits
        
        if DB_AVAILABLE and user_id:
            try:
                from flask import current_app
                with current_app.app_context():
                    # Fetch user and deduct credit immediately (must be synchronous)
                    user = User.query.get(user_id)
                    if user:
                        # Deduct 1 credit (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, 1)
                        if success:
                            db.session.commit()
                            logger.debug(f"Credit deducted (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
                            
                            # Store credit warning to append to response later
                            if credit_warning:
                                user._credit_warning = credit_warning
                        else:
                            credits_available = False
                    else:
                        credits_available = False
                    
                    # If credits available, fetch conversation history in same context
                    if credits_available:
                        # OPTIMIZATION: Use subquery to get last 10, then order ascending (no reverse needed)
                        from sqlalchemy import desc
                        subquery = db.session.query(Message.id).filter_by(user_id=user_id).order_by(desc(Message.created_at)).limit(10).subquery()
                        recent_messages = Message.query.filter(Message.id.in_(subquery)).order_by(Message.created_at.asc()).all()
                        
                        # Format as conversation history (already in chronological order)
                        for msg in recent_messages:
                            conversation_history.append({"role": "user", "content": msg.user_message})
                            if msg.bot_response:
                                conversation_history.append({"role": "assistant", "content": msg.bot_response})
                        
                        logger.info(f"Loaded {len(recent_messages)} previous messages for context")
            except Exception as db_error:
                logger.error(f"Error in consolidated DB operations: {str(db_error)}")
                conversation_history = []
                credits_available = True  # Allow response even if DB fails
        
        # If no credits, send error and return
        if not credits_available:
            response = "⚠️ You're out of credits!\n\nTo continue using the bot:\n• Use /daily to claim free credits\n• Or purchase more with /buy"
            send_message(chat_id, response)
            return
        
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
        llm_response = generate_response(text, conversation_history, use_streaming=True, update_callback=update_telegram_message, writing_mode=writing_mode)
        
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
        
        # Send credit warning if there was one stored during deduction
        if DB_AVAILABLE and user_id:
            try:
                from flask import current_app
                with current_app.app_context():
                    user = User.query.get(user_id)
                    if user and hasattr(user, '_credit_warning') and user._credit_warning:
                        send_message(chat_id, user._credit_warning)
            except Exception as e:
                logger.debug(f"Error sending credit warning: {e}")
        
        # CRITICAL: Store message SYNCHRONOUSLY for conversation memory to work
        # Credit already deducted above, so user can't use same credit twice
        message_id = None
        if DB_AVAILABLE and user_id:
            try:
                from flask import current_app
                with current_app.app_context():
                    # Create message record immediately for conversation history
                    message_record = Message(
                        user_id=user_id,
                        user_message=text,
                        bot_response=llm_response,
                        model_used=current_model,
                        credits_charged=1
                    )
                    db.session.add(message_record)
                    db.session.commit()
                    message_id = message_record.id
                    logger.info(f"Message stored synchronously for user {user_id}: {message_id}")
            except Exception as db_error:
                logger.error(f"Database error storing message: {str(db_error)}")
                # Flask-SQLAlchemy automatically rolls back on exception within app context
        
        # Store transaction record in BACKGROUND THREAD (non-critical for memory)
        # Capture Flask app object before creating thread (current_app proxy doesn't work in threads)
        if DB_AVAILABLE and user_id and message_id:
            try:
                from flask import current_app
                flask_app = current_app._get_current_object()
                
                def store_transaction_async():
                    try:
                        with flask_app.app_context():
                            transaction = Transaction(
                                user_id=user_id,
                                credits_used=1,
                                message_id=message_id,
                                transaction_type='message',
                                description=f"AI message response using {current_model}"
                            )
                            db.session.add(transaction)
                            db.session.commit()
                            logger.debug(f"Transaction stored asynchronously: message_id={message_id}")
                    except Exception as db_error:
                        logger.error(f"Async database error storing transaction: {str(db_error)}")
                        # Flask-SQLAlchemy automatically rolls back on exception within app context
                
                # Start background thread for transaction storage (non-blocking)
                threading.Thread(target=store_transaction_async, daemon=True).start()
            except Exception as e:
                logger.error(f"Error starting transaction background thread: {str(e)}")
        
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        error_message = "Sorry, I encountered an error while processing your request. Please try again later."
        send_message(chat_id, error_message)
