import os
import logging
import requests
import threading
import time
import io
import base64
from collections import deque
from typing import Deque, Dict, List, Tuple
from llm_api import generate_response, generate_image, generate_qwen_image, generate_qwen_edit_image, generate_grok_image, generate_hunyuan_image, generate_wan25_video
from models import db, User, Message, Payment, Transaction, Memory, TelegramPayment, CryptoPayment
from memory_utils import parse_memory_command, store_memory, get_user_memories, delete_memory, format_memories_for_display
from video_api import generate_video, get_video_bytes
from datetime import datetime

DEFAULT_MODEL = "deepseek/deepseek-chat-v3-0324"

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Flag to track database availability (will be set by main.py)
DB_AVAILABLE = False

# Lightweight in-memory history fallback for when the database is unavailable
IN_MEMORY_HISTORY_LIMIT = 20  # store up to 10 message pairs (user+assistant)
_in_memory_conversations: Dict[int, Deque[Tuple[str, str]]] = {}
_in_memory_lock = threading.Lock()

def _append_in_memory_history(chat_id: int | None, role: str, content: str | None) -> None:
    """Append a single message to the in-memory fallback history."""
    if chat_id is None or not content or role not in {"user", "assistant"}:
        return

    with _in_memory_lock:
        history = _in_memory_conversations.setdefault(chat_id, deque(maxlen=IN_MEMORY_HISTORY_LIMIT))
        history.append((role, content))

def _replace_in_memory_history(chat_id: int | None, history_items: List[dict]) -> None:
    """Replace the cached history with the latest database snapshot."""
    if chat_id is None:
        return

    filtered: List[Tuple[str, str]] = []
    for item in history_items[-IN_MEMORY_HISTORY_LIMIT:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            filtered.append((role, content))

    with _in_memory_lock:
        if filtered:
            _in_memory_conversations[chat_id] = deque(filtered, maxlen=IN_MEMORY_HISTORY_LIMIT)
        else:
            _in_memory_conversations.pop(chat_id, None)

def _get_in_memory_history(chat_id: int | None) -> List[dict]:
    """Retrieve a copy of the cached history for fallback usage."""
    if chat_id is None:
        return []

    with _in_memory_lock:
        stored = list(_in_memory_conversations.get(chat_id, []))

    return [{"role": role, "content": content} for role, content in stored]

def _clear_in_memory_history(chat_id: int | None) -> None:
    """Remove any cached history for the provided chat."""
    if chat_id is None:
        return

    with _in_memory_lock:
        _in_memory_conversations.pop(chat_id, None)

# Rate limiting for /video command (user_id: timestamp)
user_video_cooldown = {}

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

def store_message(user_id, user_message, bot_response, credits_cost=0, model_used=None, conversation_id=None):
    """Store a message in the database and return the message ID
    
    Args:
        user_id: User ID in database
        user_message: User's message text
        bot_response: Bot's response text
        credits_cost: Credits charged for this message (default: 0)
        model_used: Model used for generation (default: None, uses DEFAULT_MODEL)
        conversation_id: Optional conversation ID for web chat (default: None)
    
    Returns:
        int: Message ID if successful, None if failed or DB unavailable
    """
    if not DB_AVAILABLE:
        logger.debug("Database not available, skipping message storage")
        return None
    
    try:
        if model_used is None:
            model_used = DEFAULT_MODEL
        
        message_record = Message(
            user_id=user_id,
            conversation_id=conversation_id,
            user_message=user_message,
            bot_response=bot_response,
            model_used=model_used,
            credits_charged=credits_cost
        )
        db.session.add(message_record)
        db.session.commit()
        logger.debug(f"Message stored successfully: ID={message_record.id}")
        return message_record.id
    except Exception as e:
        logger.error(f"Error storing message: {str(e)}")
        return None

# Get environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Timeout for Telegram API requests to prevent worker freezing
TELEGRAM_TIMEOUT = 10  # seconds

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
                json=payload,
                timeout=TELEGRAM_TIMEOUT
            )
            result = response.json()
            
            # Check for Markdown parsing errors and retry without formatting
            if not result.get("ok") and parse_mode and "can't parse entities" in result.get("description", "").lower():
                logger.warning(f"Markdown parsing failed for chunk, retrying without formatting: {result.get('description')}")
                payload.pop("parse_mode", None)
                response = requests.post(
                    f"{BASE_URL}/sendMessage",
                    json=payload,
                    timeout=TELEGRAM_TIMEOUT
                )
                result = response.json()
            
            responses.append(result)
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
            json=payload,
            timeout=TELEGRAM_TIMEOUT
        )
        result = response.json()
        
        # Check for Markdown parsing errors and retry without formatting
        if not result.get("ok") and parse_mode and "can't parse entities" in result.get("description", "").lower():
            logger.warning(f"Markdown parsing failed, retrying without formatting: {result.get('description')}")
            payload.pop("parse_mode", None)
            response = requests.post(
                f"{BASE_URL}/sendMessage",
                json=payload,
                timeout=TELEGRAM_TIMEOUT
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
            json=payload,
            timeout=TELEGRAM_TIMEOUT
        )
        result = response.json()
        
        # Check for Markdown parsing errors and retry without formatting
        if not result.get("ok") and parse_mode and "can't parse entities" in result.get("description", "").lower():
            logger.warning(f"Markdown parsing failed during edit, retrying without formatting: {result.get('description')}")
            payload.pop("parse_mode", None)
            response = requests.post(
                f"{BASE_URL}/editMessageText",
                json=payload,
                timeout=TELEGRAM_TIMEOUT
            )
            result = response.json()
        
        # Log errors for debugging (except "message not modified" which is expected)
        if not result.get("ok") and "message is not modified" not in result.get("description", "").lower():
            logger.debug(f"Telegram edit error: {result}")
            
        return result
    except Exception as e:
        logger.debug(f"Error editing message: {str(e)}")
        return {"error": str(e)}

def delete_message(chat_id, message_id):
    """Delete a message in Telegram
    
    Args:
        chat_id (int): The ID of the chat
        message_id (int): The ID of the message to delete
    
    Returns:
        dict: The response from Telegram API
    """
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not configured")
        return {"error": "Bot token not configured"}
    
    try:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id
        }
        
        response = requests.post(
            f"{BASE_URL}/deleteMessage",
            json=payload,
            timeout=TELEGRAM_TIMEOUT
        )
        result = response.json()
        
        if not result.get("ok"):
            logger.debug(f"Failed to delete message {message_id}: {result}")
            
        return result
    except Exception as e:
        logger.debug(f"Error deleting message: {str(e)}")
        return {"error": str(e)}

def send_invoice(chat_id, title, description, payload, prices):
    """Send a payment invoice to the user (Telegram Stars)
    
    Args:
        chat_id (int): The ID of the chat
        title (str): Product name
        description (str): Product description
        payload (str): Internal identifier for this invoice
        prices (list): List of dicts with 'label' and 'amount' (in Stars)
    
    Returns:
        dict: The response from Telegram API
    """
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not configured")
        return {"error": "Bot token not configured"}
    
    try:
        payload_data = {
            "chat_id": chat_id,
            "title": title,
            "description": description,
            "payload": payload,
            "provider_token": "",  # Empty for Telegram Stars
            "currency": "XTR",  # Telegram Stars
            "prices": prices
        }
        
        response = requests.post(
            f"{BASE_URL}/sendInvoice",
            json=payload_data,
            timeout=TELEGRAM_TIMEOUT
        )
        result = response.json()
        
        if not result.get("ok"):
            logger.error(f"Failed to send invoice: {result}")
            
        return result
    except Exception as e:
        logger.error(f"Error sending invoice: {str(e)}")
        return {"error": str(e)}

def handle_pre_checkout_query(pre_checkout_query):
    """Handle pre-checkout query to validate payment before processing
    
    Args:
        pre_checkout_query (dict): The pre-checkout query from Telegram
    """
    query_id = pre_checkout_query.get("id")
    
    # Always approve (we'll validate later in successful_payment)
    try:
        response = requests.post(
            f"{BASE_URL}/answerPreCheckoutQuery",
            json={
                "pre_checkout_query_id": query_id,
                "ok": True
            },
            timeout=TELEGRAM_TIMEOUT
        )
        result = response.json()
        if result.get("ok"):
            logger.info(f"Pre-checkout query approved: {query_id}")
        else:
            logger.error(f"Failed to answer pre-checkout query: {result}")
    except Exception as e:
        logger.error(f"Error answering pre-checkout query: {str(e)}")

def handle_successful_payment(message):
    """Handle successful Telegram Stars payment
    
    Args:
        message (dict): The message containing successful_payment data
    """
    from flask import current_app
    from models import db, User, TelegramPayment, Transaction
    
    chat_id = message.get("chat", {}).get("id")
    successful_payment = message.get("successful_payment", {})
    
    # Extract payment details
    telegram_payment_charge_id = successful_payment.get("telegram_payment_charge_id")
    invoice_payload = successful_payment.get("invoice_payload")
    total_amount = successful_payment.get("total_amount")  # For XTR (Telegram Stars), amount is in Stars directly
    
    # Validate total_amount
    if total_amount is None or total_amount <= 0:
        logger.error(f"Invalid total_amount: {total_amount}")
        send_message(chat_id, "❌ Invalid payment amount. Please contact support.")
        return
    
    # IMPORTANT: For XTR currency (Telegram Stars), total_amount is already in Stars (1 Star = 1 unit)
    # This differs from fiat currencies like USD where total_amount is in smallest units (cents)
    total_stars = total_amount
    
    logger.info(f"Processing successful payment: charge_id={telegram_payment_charge_id}, payload={invoice_payload}, amount={total_stars} Stars")
    
    # Parse invoice payload to get user telegram_id and credits
    # Format: "stars_{telegram_id}_{credits}_{stars}"
    try:
        parts = invoice_payload.split("_")
        if len(parts) != 4 or parts[0] != "stars":
            raise ValueError(f"Invalid invoice payload format: {invoice_payload}")
        
        telegram_id = int(parts[1])
        credits_purchased = int(parts[2])
        stars_amount = int(parts[3])
        
        # Verify amount matches
        if total_stars != stars_amount:
            logger.error(f"Amount mismatch: expected {stars_amount} Stars, got {total_stars} Stars")
            send_message(chat_id, "❌ Payment amount mismatch. Please contact support.")
            return
        
        if not DB_AVAILABLE:
            send_message(chat_id, "❌ Database not available. Please try again later.")
            return
        
        with current_app.app_context():
            # Get user
            user = User.query.filter_by(telegram_id=telegram_id).first()
            if not user:
                logger.error(f"User not found: {telegram_id}")
                send_message(chat_id, "❌ User not found. Please contact support.")
                return
            
            # Check if payment already processed (idempotency)
            existing_payment = TelegramPayment.query.filter_by(
                telegram_payment_charge_id=telegram_payment_charge_id
            ).first()
            
            if existing_payment:
                if existing_payment.credits_added:
                    logger.warning(f"Payment already processed: {telegram_payment_charge_id}")
                    send_message(chat_id, f"✅ Payment already credited! You have {user.credits} credits.")
                    return
                else:
                    # Payment exists but credits not added - add them now
                    logger.info(f"Completing partially processed payment: {telegram_payment_charge_id}")
            else:
                # Create new payment record
                existing_payment = TelegramPayment(
                    user_id=user.id,
                    telegram_payment_charge_id=telegram_payment_charge_id,
                    invoice_payload=invoice_payload,
                    credits_purchased=credits_purchased,
                    stars_amount=stars_amount,
                    status='completed'
                )
                db.session.add(existing_payment)
            
            # Add credits to user
            user.credits += credits_purchased
            user.last_purchase_at = datetime.utcnow()
            
            # Mark payment as processed
            existing_payment.credits_added = True
            existing_payment.processed_at = datetime.utcnow()
            
            # Create transaction record
            transaction = Transaction(
                user_id=user.id,
                credits_used=-credits_purchased,  # Negative for credit addition
                transaction_type='telegram_stars_purchase',
                description=f"Purchased {credits_purchased} credits via Telegram Stars ({stars_amount} ⭐)"
            )
            db.session.add(transaction)
            
            db.session.commit()
            
            logger.info(f"Payment processed successfully: {credits_purchased} credits added to user {telegram_id}")
            
            # Send success message
            response = f"""✅ Payment Successful!

{stars_amount} ⭐ → {credits_purchased} credits

💰 Current Balance: {user.credits} credits
🎉 Thank you for your purchase!"""
            
            send_message(chat_id, response)
            
    except Exception as e:
        logger.error(f"Error processing payment: {str(e)}", exc_info=True)
        send_message(chat_id, "❌ Error processing payment. Please contact support with your payment ID.")
        if DB_AVAILABLE:
            db.session.rollback()

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
/balance - Check your credit balance
/buy - Purchase credits with volume bonuses
/clear - Clear your conversation history
/model - Switch between DeepSeek (1 credit) and GPT-4o (3 credits)
/getapikey - Get your API key for web access (private chats only)
/imagine <prompt> - High quality photorealistic images (10 credits)
/uncensored <prompt> - Fully uncensored image generation (10 credits)
/qwen <prompt> - Qwen text-to-image generation (8 credits)
/edit <prompt> - Image generation optimized for editing (8 credits)
/grok <prompt> - Stylized image generation (8 credits)
/wan <prompt> - Wan 2.1 T2V NSFW video generation (50 credits, ~60-90s)
/video <prompt> - AI text-to-video generation (50 credits, ~60-90s)
/write <request> - Professional writing mode (2 credits)

🎁 *Daily Free Credits:*
• Use /daily to claim 25 free credits
• Claimable once every 24 hours
• Daily credits expire after 48 hours
• Used automatically before purchased credits

🎨 *Image Generation:*
• /imagine <prompt> - High quality photorealistic images (10 credits)
• /uncensored <prompt> - Fully uncensored content (10 credits)
• /qwen <prompt> - Qwen text-to-image generation (8 credits)
• /edit <prompt> - Great for image editing and text (8 credits)
• /grok <prompt> - Stylized artistic content (8 credits)
• 🔒 Unlocked after first purchase

✨ *Image Editing:*
• FLUX edit: Send photo + caption (15 credits)
• Qwen edit: Send photo + caption with /edit prefix (12 credits)
Example: Send photo with caption "/edit make it darker and more dramatic"
• 🔒 Unlocked after first purchase

🎬 *Video Generation (Text-to-Video):*
• **/wan <prompt>**: Wan 2.1 T2V NSFW - New! (50 credits, ~60-90s)
  - Create NSFW videos from text descriptions
  - Example: `/wan A dragon flying over mountains`
  - 25 frames, 8 FPS, 25 steps
• **/video <prompt>**: CogVideoX - Classic (50 credits, ~60-90s)
  - Alternative text-to-video model
  - Max 200 characters per prompt

🎬 *Video Generation (Image-to-Video):*
• **/vid**: WAN 2.2 - Adjustable resolution/duration (50-78 credits)
  - 480P/720P: 5s or 8s
  - 1080P: 5s only
  - Example: Send photo with "/vid 720P 8s make it zoom dramatically"
  - Default: 480P, 5s (50 credits)
• **/img2video**: WAN 2.5 - Quick 720P 5s videos (50 credits)
  - Example: Send photo with "/img2video make it move"
• 🔒 Unlocked after first purchase

📝 *Writing Mode:*
Use /write for stories, scenes, or creative content!
• Generates at least 300 words of narrative
• Starts immediately with the story (no preamble)
• Fully uncensored creative writing
Example: /write a NSFW scene with Sydney Sweeney

🧠 *Persistent Memory:*
The AI can remember important info across sessions!
• ! memorize <text> - Store a memory (or ! remember)
• ! memories - View all your saved memories
• ! forget <id> - Delete a specific memory by ID
Example: ! memorize I love cats and prefer dark themes
💡 Memory commands are FREE (0 credits)

🤖 *AI Models (Toggle with /model):*
• DeepSeek-Chat (Default): 1 credit per message
• ChatGPT-4o (Premium): 3 credits per message
• Your choice persists across all chats
• Writing mode always costs 2 credits

💡 *Image & Video Pricing:*
• /imagine: 10 credits
• /uncensored: 10 credits
• /grok: 8 credits
• /edit: 8 credits
• FLUX editing: 15 credits
• Qwen editing: 12 credits
• /video (text-to-video): 50 credits
• Image-to-video (/vid, /img2video): 50-78 credits

💰 *Credit Packages:*
• $5 → 200 credits (2.5¢/credit)
• $10 → 400 credits (2.5¢/credit)
• $20 → 800 credits (2.5¢/credit)
• $50 → 2,000 credits (2.5¢/credit)
Bigger packs = better value!

Send any message to get an uncensored AI response!
    """
    return help_text

def process_update(update):
    """Process an update from Telegram
    
    Args:
        update (dict): The update object from Telegram
    """
    # Handle pre-checkout query (validate payment before processing)
    if "pre_checkout_query" in update:
        handle_pre_checkout_query(update["pre_checkout_query"])
        return
    
    # Handle successful payment
    if "message" in update and "successful_payment" in update["message"]:
        handle_successful_payment(update["message"])
        return
    
    # Check if the update contains a message
    if "message" not in update:
        logger.debug("Update does not contain a message")
        return
    
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    chat_type = message.get("chat", {}).get("type")
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
    
    # If there's a photo with caption, check if it's a command or generic image editing
    if photo and caption:
        # Skip for video/edit commands - they have their own handlers
        if not (caption.lower().startswith('/vid') or caption.lower().startswith('/img2video') or caption.lower().startswith('/edit')):
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
            # Define Stars packages (adjusted for Telegram's ~35% revenue share)
            STARS_PACKAGES = [
                {"stars": 385, "credits": 200, "usd": 5},
                {"stars": 770, "credits": 400, "usd": 10},
                {"stars": 1540, "credits": 800, "usd": 20},
                {"stars": 3850, "credits": 2000, "usd": 50}
            ]
            
            # Send Stars invoice buttons
            response = """⭐ *Purchase Credits with Telegram Stars*

Choose a package to pay instantly in-app (easiest option):"""
            
            send_message(chat_id, response, parse_mode="Markdown")
            
            # Send invoice for each package
            for package in STARS_PACKAGES:
                stars = package["stars"]
                credits = package["credits"]
                usd = package["usd"]
                
                title = f"{credits} Credits"
                description = f"${usd} worth of credits ({stars} ⭐)"
                payload = f"stars_{telegram_id}_{credits}_{stars}"
                # IMPORTANT: For XTR currency (Telegram Stars), amount is in Stars directly (1 Star = 1 unit)
                # This differs from fiat currencies like USD where amount is in smallest units (cents)
                prices = [{"label": f"{credits} Credits", "amount": stars}]
                
                result = send_invoice(chat_id, title, description, payload, prices)
                if not result.get("ok"):
                    logger.error(f"Failed to send invoice for {credits} credits: {result}")
            
            # Add crypto option link
            domain = os.environ.get('REPLIT_DOMAINS', '').split(',')[0] if os.environ.get('REPLIT_DOMAINS') else os.environ.get('REPLIT_DEV_DOMAIN') or 'your-app.replit.app'
            crypto_msg = f"""
🔐 *Advanced: Pay with Cryptocurrency (35% Discount!)*

Save money by paying directly with crypto - no Telegram fees!

Visit: https://{domain}/buy?telegram_id={telegram_id}

💡 Telegram Stars is instant but costs more due to processing fees."""
            
            send_message(chat_id, crypto_msg, parse_mode="Markdown")
            
            # Store command in database if available
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        message_record = Message(
                            user_id=user_id,
                            user_message=text,
                            bot_response=response + crypto_msg,
                            model_used=os.environ.get('MODEL', DEFAULT_MODEL),
                            credits_charged=0
                        )
                        db.session.add(message_record)
                        db.session.commit()
                except Exception as db_error:
                    logger.error(f"Database error storing buy command: {str(db_error)}")
            
            return
        
        # Check for /getapikey command
        if text.lower() == '/getapikey':
            # Security: Only allow /getapikey in private chats to prevent API key exposure
            if chat_type != 'private':
                response = """🔒 Security Notice

For your protection, API keys can only be retrieved in private chats.

Please send me a direct message (DM) and use /getapikey there to receive your API key securely.

⚠️ Never share your API key in group chats - anyone with your API key can use your credits!"""
                send_message(chat_id, response)
                return
            
            if DB_AVAILABLE and user:
                try:
                    from flask import current_app
                    import secrets
                    
                    with current_app.app_context():
                        # Reload user in this context
                        user = User.query.filter_by(telegram_id=telegram_id).first()
                        
                        if not user:
                            response = "❌ User not found. Please use /start first."
                        else:
                            # Generate API key if not exists
                            if not user.api_key:
                                user.api_key = secrets.token_urlsafe(48)
                                db.session.commit()
                                logger.info(f"Generated new API key for user {telegram_id}")
                            
                            response = f"""🔑 Your API Key:

`{user.api_key}`

🌐 *Web Chat:*
https://ko2bot.com/chat

📋 *How to use:*
1. Click the link above
2. Paste your API key when prompted
3. Start chatting!

💳 *Credits:* Uses the SAME credit pool as Telegram!
• Text: 1 credit/message
• Balance: {user.credits + user.daily_credits} credits

⚠️ *Keep this key private!* Anyone with this key can use your credits.

Use /buy to purchase more credits or /daily for free credits.
"""
                except Exception as db_error:
                    logger.error(f"Database error getting API key: {str(db_error)}")
                    db.session.rollback()
                    response = "❌ Error generating API key. Please try again."
            else:
                response = "❌ API key feature requires database access."
            
            # Send response with Markdown for code formatting
            send_message(chat_id, response, parse_mode="Markdown")
            return
        
        # Check for /model command (switch between DeepSeek and GPT-4o)
        if text.lower() == '/model':
            if DB_AVAILABLE and user:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        # Reload user to get CURRENT preferred_model from database (not stale value)
                        fresh_user = User.query.filter_by(telegram_id=telegram_id).first()
                        if not fresh_user:
                            send_message(chat_id, "❌ User not found. Please try /start first.")
                            return
                        
                        # Get current model from database
                        current_model = fresh_user.preferred_model or 'deepseek/deepseek-chat-v3-0324'
                        
                        # Toggle model
                        if 'deepseek' in current_model.lower():
                            new_model = 'openai/chatgpt-4o-latest'
                            new_model_name = 'ChatGPT-4o'
                            cost_per_message = '2 credits'
                        else:
                            new_model = 'deepseek/deepseek-chat-v3-0324'
                            new_model_name = 'DeepSeek v3-0324'
                            cost_per_message = '1 credit'
                        
                        # Update user's preferred model
                        fresh_user.preferred_model = new_model
                        db.session.commit()
                        
                        response = f"✅ Model switched to *{new_model_name}*\n\n💬 Cost: {cost_per_message} per message\n\nUse /model again to switch back."
                        logger.info(f"User {telegram_id} switched model to {new_model}")
                except Exception as db_error:
                    logger.error(f"Database error switching model: {str(db_error)}")
                    db.session.rollback()
                    response = "❌ Error switching model. Please try again."
            else:
                response = "❌ Model switching requires database access."
            
            send_message(chat_id, response, parse_mode="Markdown")
            return
        
        # Check for /clear command
        if text.lower() == '/clear':
            had_fallback_history = bool(_get_in_memory_history(chat_id))
            _clear_in_memory_history(chat_id)

            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        # First, delete all transactions that reference messages for this user
                        message_ids = [msg.id for msg in Message.query.filter_by(user_id=user_id).all()]

                        if message_ids:
                            Transaction.query.filter(Transaction.message_id.in_(message_ids)).delete(synchronize_session=False)

                        deleted_count = Message.query.filter_by(user_id=user_id).delete()
                        db.session.commit()

                        response = f"✅ Conversation history cleared!\n\n{deleted_count} messages deleted from your history.\n\nYou can now start a fresh conversation with full system prompt effectiveness."
                        logger.info(f"Cleared {deleted_count} messages for user {user_id}")
                except Exception as db_error:
                    logger.error(f"Database error clearing history: {str(db_error)}")
                    db.session.rollback()
                    response = "❌ Error clearing conversation history. Please try again."
            else:
                if had_fallback_history:
                    response = "✅ Conversation history cleared from temporary storage. Database history is unavailable right now."
                else:
                    response = "❌ Conversation history feature requires database access."

            send_message(chat_id, response)
            return
        
        # Check for /cogvideo command (CogVideoX-5B text-to-video)
        if text.lower() == '/cogvideo' or text.lower().startswith('/cogvideo '):
            from llm_api import generate_cogvideox_video
            
            # Extract prompt
            if text.lower() == '/cogvideo':
                response = """🎬 *CogVideoX-5B Video Generation* (Text-to-Video)

*Create videos from text descriptions!*

*Usage:*
`/cogvideo [your description]`

*Examples:*
• `/cogvideo A dragon flying over a neon city at night`
• `/cogvideo Waves crashing on a beach during sunset`
• `/cogvideo A robot dancing in a futuristic warehouse`

*Pricing:*
• 60 credits per video (16 frames, 8 FPS, ~2 seconds)

*Note:* This generates videos from scratch using AI on our GPU server.
For image-to-video, use `/vid` or `/img2video` instead."""
                
                send_message(chat_id, response, parse_mode="Markdown")
                return
            
            # Extract prompt after /cogvideo
            prompt = text[10:].strip()
            
            if not prompt:
                send_message(chat_id, "❌ Please provide a description after /cogvideo")
                return
            
            logger.info(f"Processing CogVideoX video generation: {prompt[:50]}...")
            
            # Credit cost
            VIDEO_CREDITS = 60
            
            # Check if user has made first purchase
            if user.credits == 0 and user.images_generated == 0:
                send_message(
                    chat_id, 
                    "🔒 *Video generation requires a purchase first*\n\n"
                    "To unlock video generation:\n"
                    "• Use /buy to purchase credits via Telegram Stars\n"
                    "• Or use /crypto for cryptocurrency payment\n\n"
                    "After your first purchase, you'll have access to all video features!",
                    parse_mode="Markdown"
                )
                return
            
            # Check balance upfront
            available_balance = user.credits + user.daily_credits
            
            if available_balance < VIDEO_CREDITS:
                send_message(
                    chat_id,
                    f"❌ Insufficient credits!\n\n"
                    f"💰 Available: {available_balance} credits\n"
                    f"🎬 Video cost: {VIDEO_CREDITS} credits\n"
                    f"📊 Need: {VIDEO_CREDITS - available_balance} more credits\n\n"
                    f"Use /buy to purchase more credits."
                )
                return
            
            # Deduct credits upfront
            try:
                success, daily_used, purchased_used, credit_warning = deduct_credits(user, VIDEO_CREDITS)
                if not success:
                    total = user.credits + user.daily_credits
                    send_message(
                        chat_id,
                        f"⚠️ Insufficient credits!\n\n"
                        f"You have {total} credits but need {VIDEO_CREDITS} credits to generate a video.\n\n"
                        f"Use /buy to purchase more credits or /daily to claim free credits."
                    )
                    return
                
                logger.info(f"✓ Deducted {VIDEO_CREDITS} credits upfront for CogVideoX video (daily: {daily_used}, purchased: {purchased_used})")
            except Exception as e:
                logger.error(f"Error deducting credits: {str(e)}")
                send_message(chat_id, "❌ Error processing credits. Please try again.")
                return
            
            # Send processing message
            processing_msg = send_message(
                chat_id,
                f"🎬 *Generating video on GPU server...*\n\n"
                f"📝 Prompt: {prompt[:100]}\n"
                f"💰 Cost: {VIDEO_CREDITS} credits\n\n"
                f"⏳ This may take 2-5 minutes. Please wait...",
                parse_mode="Markdown"
            )
            
            try:
                # Generate video on GPU server
                result = generate_cogvideox_video(prompt=prompt)
                
                if result["status"] == "ok":
                    video_base64 = result.get("video_base64")
                    generation_ms = result.get("ms", 0)
                    generation_sec = generation_ms / 1000
                    
                    logger.info(f"✅ CogVideoX video generated ({generation_sec:.1f}s)")
                    
                    if not video_base64:
                        logger.error("No video_base64 in response")
                        # Refund to exact buckets that were deducted
                        user.daily_credits += daily_used
                        user.credits += purchased_used
                        db.session.commit()
                        logger.info(f"Refunded {VIDEO_CREDITS} credits (daily: {daily_used}, purchased: {purchased_used})")
                        send_message(
                            chat_id,
                            f"❌ Video generated but not included in response.\n\n"
                            f"✅ {VIDEO_CREDITS} credits have been refunded."
                        )
                        return
                    
                    try:
                        # Decode base64 video
                        video_bytes = base64.b64decode(video_base64)
                        
                        logger.info(f"✅ Video decoded: {len(video_bytes)} bytes")
                        
                        # Send video to user via Telegram API
                        files = {
                            'video': ('cogvideo.mp4', io.BytesIO(video_bytes), 'video/mp4')
                        }
                        data = {
                            'chat_id': chat_id,
                            'caption': (
                                f"🎬 *CogVideoX Video Generated!*\n\n"
                                f"📝 Prompt: _{prompt[:100]}_\n"
                                f"⏱️ Generation time: {generation_sec:.1f}s\n"
                                f"💰 Credits remaining: {user.credits + user.daily_credits}"
                            ),
                            'parse_mode': 'Markdown'
                        }
                        
                        response = requests.post(
                            f"{BASE_URL}/sendVideo",
                            files=files,
                            data=data,
                            timeout=60
                        )
                        
                        if response.status_code == 200:
                            logger.info(f"✅ Video sent successfully to user {chat_id}")
                        else:
                            logger.error(f"Failed to send video: {response.text}")
                            raise Exception(f"Telegram API error: {response.status_code}")
                    
                    except Exception as decode_error:
                        logger.error(f"Failed to decode/send video: {str(decode_error)}")
                        # Refund to exact buckets that were deducted
                        user.daily_credits += daily_used
                        user.credits += purchased_used
                        db.session.commit()
                        logger.info(f"Refunded {VIDEO_CREDITS} credits (daily: {daily_used}, purchased: {purchased_used})")
                        send_message(
                            chat_id,
                            f"❌ Failed to process video: {str(decode_error)}\n\n"
                            f"✅ {VIDEO_CREDITS} credits have been refunded."
                        )
                    
                else:
                    error_msg = result.get("error", "Unknown error")
                    logger.error(f"CogVideoX video generation failed: {error_msg}")
                    
                    # Refund to exact buckets that were deducted
                    user.daily_credits += daily_used
                    user.credits += purchased_used
                    db.session.commit()
                    logger.info(f"Refunded {VIDEO_CREDITS} credits (daily: {daily_used}, purchased: {purchased_used})")
                    
                    send_message(
                        chat_id,
                        f"❌ Video generation failed: {error_msg}\n\n"
                        f"✅ {VIDEO_CREDITS} credits have been refunded to your account."
                    )
            
            except Exception as e:
                logger.error(f"Error in CogVideoX video generation: {str(e)}")
                
                # Refund to exact buckets that were deducted
                user.daily_credits += daily_used
                user.credits += purchased_used
                db.session.commit()
                logger.info(f"Refunded {VIDEO_CREDITS} credits (daily: {daily_used}, purchased: {purchased_used})")
                
                send_message(
                    chat_id,
                    f"❌ Error generating video: {str(e)}\n\n"
                    f"✅ {VIDEO_CREDITS} credits have been refunded."
                )
            
            return
        
        # Check for /video command (Wan 2.1 T2V text-to-video)
        if text.lower() == '/video' or text.lower().startswith('/video '):
            # Extract prompt
            if text.lower() == '/video':
                response = """🎬 *AI Video Generation*

*Create videos from text descriptions!*

*Usage:*
`/video <your prompt>`

*Examples:*
• `/video A dragon flying over mountains`
• `/video A rocket launch`
• `/video Ocean waves at sunset`

*Pricing:*
• 50 credits per video (~30 seconds generation time)

*Note:* Maximum 200 characters per prompt."""
                
                send_message(chat_id, response, parse_mode="Markdown")
                return
            
            # Extract prompt after /video
            prompt = text[7:].strip()
            
            if not prompt:
                send_message(chat_id, "❌ Please provide a prompt after /video")
                return
            
            # Check prompt length
            if len(prompt) > 200:
                send_message(chat_id, "❌ Prompt too long. Maximum 200 characters.")
                return
            
            logger.info(f"Processing /video generation: {prompt[:50]}...")
            
            # Credit cost
            VIDEO_CREDITS = 50
            
            # Rate limiting: TEMPORARILY DISABLED FOR TESTING
            # now = time.time()
            # if telegram_id in user_video_cooldown:
            #     elapsed = now - user_video_cooldown[telegram_id]
            #     if elapsed < 60:
            #         send_message(
            #             chat_id,
            #             f"⏳ Please wait {60-int(elapsed)} seconds before generating another video."
            #         )
            #         return
            
            # Check if user exists
            if not user:
                send_message(chat_id, "❌ User not found. Please use /start first.")
                return
            
            # Check balance upfront
            total_credits = user.credits + user.daily_credits
            
            if total_credits < VIDEO_CREDITS:
                send_message(
                    chat_id,
                    f"❌ Insufficient credits!\n\n"
                    f"💰 Available: {total_credits} credits\n"
                    f"🎬 Video cost: {VIDEO_CREDITS} credits\n"
                    f"📊 Need: {VIDEO_CREDITS - total_credits} more credits\n\n"
                    f"Use /buy to purchase more credits or /daily to claim free credits."
                )
                return
            
            # Deduct credits upfront
            try:
                success, daily_used, purchased_used, credit_warning = deduct_credits(user, VIDEO_CREDITS)
                if not success:
                    send_message(
                        chat_id,
                        f"⚠️ Insufficient credits!\n\n"
                        f"You have {total_credits} credits but need {VIDEO_CREDITS} credits to generate a video.\n\n"
                        f"Use /buy to purchase more credits or /daily to claim free credits."
                    )
                    return
                
                db.session.commit()
                logger.info(f"✓ Deducted {VIDEO_CREDITS} credits upfront for /video (daily: {daily_used}, purchased: {purchased_used})")
            except Exception as e:
                logger.error(f"Error deducting credits: {str(e)}")
                send_message(chat_id, "❌ Error processing credits. Please try again.")
                return
            
            # Update rate limit - TEMPORARILY DISABLED
            # user_video_cooldown[telegram_id] = now
            
            # Send processing message
            send_message(
                chat_id,
                f"🎬 *Generating video...*\n\n"
                f"Prompt: _{prompt}_\n"
                f"⏱ This takes ~60-90 seconds. Please wait...",
                parse_mode="Markdown"
            )
            
            # Generate video in background thread to avoid webhook timeout
            from flask import current_app
            app = current_app._get_current_object()
            
            def generate_video_background():
                """Background video generation with comprehensive error handling"""
                try:
                    with app.app_context():
                        # Re-fetch user to avoid DetachedInstanceError
                        from models import User
                        user_obj = db.session.query(User).filter_by(telegram_id=telegram_id).first()
                        
                        # Generate video (Wan 2.1 T2V NSFW-enabled)
                        result = generate_video(prompt, frames=25, steps=25)
                        
                        # Handle generation failure
                        if result["status"] == "error":
                            error_msg = result.get("error", "Unknown error")
                            logger.error(f"Video generation failed: {error_msg}")
                            
                            # Refund credits to exact buckets that were deducted
                            user_obj.daily_credits += daily_used
                            user_obj.credits += purchased_used
                            db.session.commit()
                            logger.info(f"Refunded {VIDEO_CREDITS} credits (daily: {daily_used}, purchased: {purchased_used})")
                            
                            send_message(
                                chat_id,
                                f"❌ *Video generation failed*\n\n"
                                f"Error: {error_msg}\n\n"
                                f"✅ {VIDEO_CREDITS} credits have been refunded.",
                                parse_mode="Markdown"
                            )
                            return
                        
                        # Extract video bytes from base64 response (Wan API)
                        try:
                            video_bytes = get_video_bytes(result)
                            if not video_bytes:
                                raise Exception("Failed to extract video from response")
                        except Exception as extract_err:
                            logger.error(f"Video extraction failed: {extract_err}")

                            # Refund credits to exact buckets that were deducted
                            user_obj.daily_credits += daily_used
                            user_obj.credits += purchased_used
                            db.session.commit()
                            logger.info(f"Refunded {VIDEO_CREDITS} credits (daily: {daily_used}, purchased: {purchased_used})")

                            send_message(
                                chat_id,
                                f"❌ Video generated but extraction failed.\n\n"
                                f"✅ {VIDEO_CREDITS} credits have been refunded. Please try again."
                            )
                            return
                        
                        # Send video to user
                        try:
                            files = {
                                'video': ('generated_video.mp4', io.BytesIO(video_bytes), 'video/mp4')
                            }
                            data = {
                                'chat_id': chat_id,
                                'caption': (
                                    f"✅ *Video generated!*\n"
                                    f"Prompt: _{prompt}_\n"
                                    f"Model: Wan 2.1 T2V NSFW (640x384, 8fps)\n"
                                    f"Time: {result.get('ms', 0)/1000:.1f}s\n"
                                    f"Frames: {result.get('frames', 25)}\n"
                                    f"Steps: {result.get('steps', 25)}\n"
                                    f"Credits remaining: {user_obj.credits + user_obj.daily_credits}"
                                ),
                                'parse_mode': 'Markdown'
                            }
                            
                            response = requests.post(
                                f"{BASE_URL}/sendVideo",
                                files=files,
                                data=data,
                                timeout=60
                            )
                            
                            if response.status_code == 200:
                                logger.info(f"✅ Video sent successfully to user {telegram_id}")
                            else:
                                logger.error(f"Failed to send video: {response.text}")
                                raise Exception(f"Telegram API error: {response.status_code}")
                            
                        except Exception as e:
                            logger.error(f"Failed to send video: {e}")
                            send_message(
                                chat_id,
                                f"❌ Failed to send video. Credits were deducted. Contact support."
                            )
                
                except Exception as e:
                    logger.error(f"CRITICAL: Wan 2.1 T2V background thread crashed: {str(e)}", exc_info=True)
                    
                    try:
                        with app.app_context():
                            # Re-fetch user
                            from models import User
                            user_obj = db.session.query(User).filter_by(telegram_id=telegram_id).first()
                            if user_obj:
                                # Refund credits
                                user_obj.daily_credits += daily_used
                                user_obj.credits += purchased_used
                                db.session.commit()
                                logger.info(f"Refunded {VIDEO_CREDITS} credits after background thread crash")
                    except Exception as refund_err:
                        logger.error(f"Could not refund credits after crash (CRITICAL): {str(refund_err)}")
                    
                    send_message(
                        chat_id,
                        f"❌ Unexpected error during video generation.\n\n"
                        f"✅ {VIDEO_CREDITS} credits have been refunded."
                    )
            
            # Start background thread
            thread = threading.Thread(target=generate_video_background)
            thread.start()
            
            return
        
        # Check for /vid command (text-only - explain proper usage)
        if text.lower() == '/vid' or text.lower().startswith('/vid '):
            response = """🎬 *WAN 2.2 Video Generation* (Image-to-Video)

To create a video, you need to:

1️⃣ Attach or send a photo first
2️⃣ Add a caption starting with `/vid`

*Examples:*
• Send photo + caption: `/vid make the clouds move slowly`
• Send photo + caption: `/vid 720P 8s zoom in dramatically`
• Send photo + caption: `/vid 1080P 5s make it epic`

*Pricing:*
• 480P, 5s: 50 credits (default)
• 720P, 5s: 60 credits
• 720P, 8s: 70 credits
• 1080P, 5s: 78 credits

*Resolution & Duration Options:*
• 480P/720P: 5s or 8s duration
• 1080P: 5s only

📸 Try sending a photo with `/vid` in the caption!"""

            send_message(chat_id, response, parse_mode="Markdown")
            return

        # Check for /wan command (Wan 2.1 T2V - completely fresh implementation)
        if text.lower() == '/wan' or text.lower().startswith('/wan '):
            from video_api import generate_wan_t2v, get_video_bytes

            if text.lower() == '/wan':
                response = """🎬 *Wan 2.1 T2V* - Text-to-Video NSFW

*Create videos from text descriptions!*

*Usage:*
`/wan <your prompt>`

*Examples:*
• `/wan A dragon flying over mountains`
• `/wan Ocean waves at sunset`
• `/wan A rocket launching into space`

*Specs:*
• Model: Wan 2.1 T2V NSFW
• Frames: 25 | FPS: 8 | Steps: 25
• Generation time: ~60-90 seconds

*Cost:* 50 credits per video"""
                send_message(chat_id, response, parse_mode="Markdown")
                return

            # Extract prompt
            prompt = text[5:].strip()
            if not prompt:
                send_message(chat_id, "❌ Please provide a prompt after /wan")
                return

            # Check prompt length
            if len(prompt) > 2000:
                send_message(chat_id, "❌ Prompt too long. Maximum 2000 characters.")
                return

            logger.info(f"🎬 /wan command: {prompt[:50]}...")

            # Credit cost
            WAN_CREDITS = 50

            # Check user exists
            if not user:
                send_message(chat_id, "❌ User not found. Please use /start first.")
                return

            # Check balance
            total_credits = user.credits + user.daily_credits
            if total_credits < WAN_CREDITS:
                send_message(
                    chat_id,
                    f"❌ Insufficient credits!\n\n"
                    f"💰 Available: {total_credits} credits\n"
                    f"🎬 Wan video cost: {WAN_CREDITS} credits\n\n"
                    f"Use /buy to purchase more credits or /daily to claim free credits."
                )
                return

            # Deduct credits upfront
            try:
                success, daily_used, purchased_used, credit_warning = deduct_credits(user, WAN_CREDITS)
                if not success:
                    send_message(chat_id, f"❌ Error deducting credits. Please try /start again.")
                    return

                db.session.commit()
                logger.info(f"✓ Deducted {WAN_CREDITS} credits for /wan (daily: {daily_used}, purchased: {purchased_used})")
            except Exception as e:
                logger.error(f"Error deducting credits: {str(e)}")
                send_message(chat_id, "❌ Error processing credits. Please try again.")
                return

            # Send processing message
            send_message(
                chat_id,
                f"🎬 *Generating Wan 2.1 T2V video...*\n\n"
                f"Prompt: _{prompt}_\n"
                f"⏱ This takes ~60-90 seconds. Please wait...",
                parse_mode="Markdown"
            )

            # Generate in background thread
            from flask import current_app
            app = current_app._get_current_object()

            def generate_wan_background():
                """Background Wan 2.1 T2V generation"""
                try:
                    with app.app_context():
                        from models import User
                        user_obj = db.session.query(User).filter_by(telegram_id=telegram_id).first()

                        # Generate video
                        result = generate_wan_t2v(prompt, frames=25, steps=25)

                        # Handle generation failure
                        if result["status"] == "error":
                            error_msg = result.get("error", "Unknown error")
                            logger.error(f"Wan generation failed: {error_msg}")

                            # Refund credits
                            user_obj.daily_credits += daily_used
                            user_obj.credits += purchased_used
                            db.session.commit()
                            logger.info(f"Refunded {WAN_CREDITS} credits")

                            send_message(
                                chat_id,
                                f"❌ *Wan video generation failed*\n\n"
                                f"Error: {error_msg}\n\n"
                                f"✅ {WAN_CREDITS} credits have been refunded.",
                                parse_mode="Markdown"
                            )
                            return

                        # Extract video bytes
                        try:
                            video_bytes = get_video_bytes(result)
                            if not video_bytes:
                                raise Exception("Failed to extract video from response")
                        except Exception as extract_err:
                            logger.error(f"Video extraction failed: {extract_err}")

                            # Refund credits
                            user_obj.daily_credits += daily_used
                            user_obj.credits += purchased_used
                            db.session.commit()

                            send_message(
                                chat_id,
                                f"❌ Video generated but extraction failed.\n\n"
                                f"✅ {WAN_CREDITS} credits have been refunded."
                            )
                            return

                        # Send video to user
                        try:
                            files = {'video': ('wan_video.mp4', io.BytesIO(video_bytes), 'video/mp4')}
                            data = {
                                'chat_id': chat_id,
                                'caption': (
                                    f"✅ *Wan 2.1 T2V Video!*\n"
                                    f"Prompt: _{prompt}_\n"
                                    f"Model: Wan 2.1 T2V NSFW\n"
                                    f"Time: {result.get('ms', 0)/1000:.1f}s\n"
                                    f"Frames: {result.get('frames', 25)} | FPS: 8\n"
                                    f"Credits remaining: {user_obj.credits + user_obj.daily_credits}"
                                ),
                                'parse_mode': 'Markdown'
                            }

                            response = requests.post(
                                f"{BASE_URL}/sendVideo",
                                files=files,
                                data=data,
                                timeout=60
                            )

                            if response.status_code == 200:
                                logger.info(f"✅ Wan video sent to user {telegram_id}")
                            else:
                                logger.error(f"Failed to send video: {response.text}")

                        except Exception as e:
                            logger.error(f"Failed to send video: {e}")
                            send_message(chat_id, f"❌ Failed to send video. Contact support.")

                except Exception as e:
                    logger.error(f"Wan background thread crashed: {str(e)}", exc_info=True)
                    send_message(chat_id, f"❌ Unexpected error. {WAN_CREDITS} credits refunded.")

            # Start background thread
            thread = threading.Thread(target=generate_wan_background)
            thread.start()
            return

        # Admin-only /stats command
        if text.lower() == '/stats':
            ADMIN_TELEGRAM_ID = 1230053047
            
            if telegram_id != ADMIN_TELEGRAM_ID:
                send_message(chat_id, "⛔ *ADMIN ACCESS REQUIRED*\n\nThis command is restricted to system administrators only.", parse_mode="Markdown")
                return
            
            if DB_AVAILABLE:
                try:
                    from flask import current_app
                    from sqlalchemy import func
                    from datetime import timedelta
                    
                    with current_app.app_context():
                        # Time window: Last 7 days
                        now = datetime.utcnow()
                        cutoff_time = now - timedelta(days=7)
                        
                        # Core platform stats
                        total_users = User.query.count()
                        total_messages = Message.query.count()
                        
                        # Revenue stats - Last 7 days (convert Telegram Stars to USD: 1 Star ≈ $0.013)
                        telegram_stars_7d = db.session.query(func.sum(TelegramPayment.stars_amount)).filter(
                            TelegramPayment.created_at >= cutoff_time
                        ).scalar() or 0
                        revenue_telegram_7d = telegram_stars_7d * 0.013
                        revenue_crypto_7d = db.session.query(func.sum(CryptoPayment.price_amount)).filter(
                            CryptoPayment.created_at >= cutoff_time,
                            CryptoPayment.payment_status.in_(['confirmed', 'finished'])
                        ).scalar() or 0
                        revenue_7d = revenue_telegram_7d + revenue_crypto_7d
                        
                        # Credits sold - Last 7 days
                        credits_telegram_7d = db.session.query(func.sum(TelegramPayment.credits_purchased)).filter(
                            TelegramPayment.created_at >= cutoff_time
                        ).scalar() or 0
                        credits_crypto_7d = db.session.query(func.sum(CryptoPayment.credits_purchased)).filter(
                            CryptoPayment.created_at >= cutoff_time,
                            CryptoPayment.payment_status.in_(['confirmed', 'finished'])
                        ).scalar() or 0
                        credits_sold_7d = credits_telegram_7d + credits_crypto_7d
                        
                        # Lock health
                        users_with_locks = User.query.filter(User.processing_since.isnot(None)).all()
                        total_locks = len(users_with_locks)
                        stuck_locks = sum(1 for u in users_with_locks if (now - u.processing_since).total_seconds() > 300)
                        active_locks = sum(1 for u in users_with_locks if (now - u.processing_since).total_seconds() <= 60)
                        warning_locks = total_locks - stuck_locks - active_locks
                        
                        if stuck_locks > 0:
                            lock_status = "🔴 NEEDS ATTENTION"
                        elif warning_locks > 0:
                            lock_status = "🟡 MONITORING"
                        else:
                            lock_status = "🟢 HEALTHY"
                        
                        # Content generation stats - Last 7 days (using Transaction for accuracy)
                        videos_7d = Transaction.query.filter(
                            Transaction.created_at >= cutoff_time,
                            Transaction.transaction_type == 'video_generation'
                        ).count()
                        
                        images_7d = Transaction.query.filter(
                            Transaction.created_at >= cutoff_time,
                            Transaction.transaction_type.in_(['image_generation', 'qwen_image_generation', 'grok_image_generation', 'hunyuan_image_generation'])
                        ).count()
                        
                        edits_7d = Transaction.query.filter(
                            Transaction.created_at >= cutoff_time,
                            Transaction.transaction_type.in_(['image_editing', 'qwen_image_editing'])
                        ).count()
                        
                        texts_7d = Message.query.filter(
                            Message.created_at >= cutoff_time,
                            Message.model_used.in_(['deepseek/deepseek-chat-v3-0324', 'openai/chatgpt-4o-latest'])
                        ).count()
                        
                        # Image style breakdown - Last 7 days
                        flux_7d = Transaction.query.filter(
                            Transaction.created_at >= cutoff_time,
                            Transaction.transaction_type == 'image_generation'
                        ).count()
                        qwen_7d = Transaction.query.filter(
                            Transaction.created_at >= cutoff_time,
                            Transaction.transaction_type == 'qwen_image_generation'
                        ).count()
                        grok_7d = Transaction.query.filter(
                            Transaction.created_at >= cutoff_time,
                            Transaction.transaction_type == 'grok_image_generation'
                        ).count()
                        hunyuan_7d = Transaction.query.filter(
                            Transaction.created_at >= cutoff_time,
                            Transaction.transaction_type == 'hunyuan_image_generation'
                        ).count()
                        
                        # Content type breakdown (percentages)
                        total_content = images_7d + videos_7d + edits_7d + texts_7d
                        if total_content > 0:
                            img_pct = (images_7d / total_content) * 100
                            vid_pct = (videos_7d / total_content) * 100
                            edit_pct = (edits_7d / total_content) * 100
                            text_pct = (texts_7d / total_content) * 100
                        else:
                            img_pct = vid_pct = edit_pct = text_pct = 0
                        
                        # Model preference breakdown (all users)
                        deepseek_users = User.query.filter(
                            (User.preferred_model == 'deepseek/deepseek-chat-v3-0324') | 
                            (User.preferred_model.is_(None))
                        ).count()
                        gpt4o_users = User.query.filter(User.preferred_model == 'openai/chatgpt-4o-latest').count()
                        
                        # Sample popular prompts from last 7 days (get 5 random image descriptions)
                        sample_prompts = db.session.query(Transaction.description).filter(
                            Transaction.created_at >= cutoff_time,
                            Transaction.transaction_type.in_(['image_generation', 'qwen_image_generation', 'grok_image_generation', 'hunyuan_image_generation']),
                            Transaction.description.isnot(None)
                        ).order_by(func.random()).limit(5).all()
                        
                        # Format response with content-focused analytics
                        response = f"""🔥 *CONTENT INTELLIGENCE - LAST 7 DAYS* 🔥

💎 *SYSTEM STATUS:*
- Mode: *FULLY OPERATIONAL*
- Lock Health: *{lock_status}*
- Active Workers: {active_locks}/{total_locks}
- Total Users: *{total_users:,}*
- Total Messages: *{total_messages:,}*

📊 *LAST 7 DAYS REVENUE:*
- Total: *${revenue_7d:.2f}*
  • Telegram Stars: ${revenue_telegram_7d:.2f}
  • Crypto: ${revenue_crypto_7d:.2f}
- Credits Sold: *{credits_sold_7d:,}*

🎨 *CONTENT CREATED (LAST 7 DAYS):*
- 🖼️ Images: *{images_7d}* ({img_pct:.1f}%)
- 🎬 Videos: *{videos_7d}* ({vid_pct:.1f}%)
- ✏️ Edits: *{edits_7d}* ({edit_pct:.1f}%)
- 💬 Texts: *{texts_7d}* ({text_pct:.1f}%)

🎭 *IMAGE STYLE BREAKDOWN:*
- FLUX (Photorealistic): {flux_7d}
- Hunyuan (Uncensored): {hunyuan_7d}
- Grok (Stylized): {grok_7d}
- Qwen (Quick): {qwen_7d}

🤖 *MODEL PREFERENCE:*
- DeepSeek Users: {deepseek_users} ({deepseek_users/max(total_users,1)*100:.1f}%)
- GPT-4o Users: {gpt4o_users} ({gpt4o_users/max(total_users,1)*100:.1f}%)"""
                        
                        # Add sample prompts if available
                        if sample_prompts:
                            response += "\n\n💡 *SAMPLE PROMPTS (WHAT USERS CREATE):*"
                            for i, (desc,) in enumerate(sample_prompts, 1):
                                # Extract prompt from description (format: "Image generation: prompt")
                                if desc and ':' in desc:
                                    prompt_text = desc.split(':', 1)[1].strip()[:80]
                                    response += f"\n{i}. {prompt_text}..."
                        
                        response += "\n\n//ADMIN_PANEL:LO_OK"
                        
                        send_message(chat_id, response, parse_mode="Markdown")
                        logger.info(f"Admin stats retrieved by {username} ({telegram_id})")
                        return
                        
                except Exception as db_error:
                    logger.error(f"Error generating admin stats: {str(db_error)}")
                    send_message(chat_id, f"❌ Error generating stats: {str(db_error)}")
                    return
            else:
                send_message(chat_id, "❌ Stats require database access.")
                return

        # Admin-only /unlock_video command
        if text.lower().startswith('/unlock_video'):
            ADMIN_TELEGRAM_ID = 1230053047

            if telegram_id != ADMIN_TELEGRAM_ID:
                send_message(chat_id, "⛔ *ADMIN ACCESS REQUIRED*\n\nThis command is restricted to system administrators only.", parse_mode="Markdown")
                return

            if DB_AVAILABLE:
                try:
                    from flask import current_app
                    from datetime import datetime

                    parts = text.split()
                    if len(parts) == 1:
                        # Unlock self
                        target_telegram_id = telegram_id
                    elif len(parts) == 2:
                        # Unlock specific user by telegram ID
                        try:
                            target_telegram_id = int(parts[1])
                        except ValueError:
                            send_message(chat_id, "❌ Invalid Telegram ID. Usage: /unlock_video [telegram_id]")
                            return
                    else:
                        send_message(chat_id, "❌ Usage: /unlock_video [telegram_id]\n\nOmit telegram_id to unlock yourself.")
                        return

                    with current_app.app_context():
                        user = User.query.filter_by(telegram_id=target_telegram_id).first()

                        if not user:
                            send_message(chat_id, f"❌ User with Telegram ID {target_telegram_id} not found.")
                            return

                        if user.last_purchase_at:
                            send_message(
                                chat_id,
                                f"✓ User @{user.username or 'unknown'} (ID: {target_telegram_id}) already has video unlocked.\n"
                                f"Last purchase: {user.last_purchase_at}"
                            )
                        else:
                            user.last_purchase_at = datetime.utcnow()
                            db.session.commit()
                            send_message(
                                chat_id,
                                f"✅ Video generation unlocked for @{user.username or 'unknown'} (ID: {target_telegram_id})\n"
                                f"Set last_purchase_at to {user.last_purchase_at}"
                            )
                            logger.info(f"Admin {telegram_id} unlocked video for user {target_telegram_id}")

                except Exception as db_error:
                    logger.error(f"Error unlocking video: {str(db_error)}")
                    send_message(chat_id, f"❌ Error: {str(db_error)}")
                    return
            else:
                send_message(chat_id, "❌ This command requires database access.")
                return

        # RATE LIMITING: DISABLED to allow reflection prompts to complete
        # The reflection system makes internal API calls that were being blocked
        # if DB_AVAILABLE and user:
        #     try:
        #         from flask import current_app
        #         with current_app.app_context():
        #             # Reload user to get fresh processing_since value
        #             user = User.query.filter_by(telegram_id=telegram_id).first()
        #             if user:
        #                 now = datetime.utcnow()
        #                 if user.processing_since:
        #                     # Check if processing started within last 60 seconds
        #                     time_elapsed = (now - user.processing_since).total_seconds()
        #                     if time_elapsed < 60:
        #                         logger.warning(f"Rate limit: User {telegram_id} has message processing (started {time_elapsed:.1f}s ago)")
        #                         send_message(chat_id, "⏳ Please wait for your previous message to finish processing before sending another one...")
        #                         return
        #                     else:
        #                         logger.info(f"Rate limit: Clearing stale processing lock (started {time_elapsed:.1f}s ago)")
        #                 
        #                 # Set processing lock
        #                 user.processing_since = now
        #                 db.session.commit()
        #                 logger.debug(f"Rate limit: Set processing lock for user {telegram_id}")
        #     except Exception as db_error:
        #         logger.error(f"Rate limit check error: {str(db_error)}")
        #         # Continue without rate limiting if there's an error
            
        # Check for /imagine command (image generation)
        if text.lower().startswith('/imagine '):
            prompt = text[9:].strip()  # Remove '/imagine ' prefix
            
            if not prompt:
                send_message(chat_id, "❌ Please provide a prompt.\n\nExample: /imagine a cat in a tree at sunset")
                return
            
            # OPTIMIZATION: Check balance and deduct credits upfront (before generation)
            pending_credit_warning = None
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        user = User.query.get(user_id)
                        if not user:
                            logger.error(f"User not found for image generation: {user_id}")
                            send_message(chat_id, "❌ User account not found. Please try /start first.")
                            return
                        
                        # IMAGE GENERATION PAYWALL: Check if user has ever purchased
                        if not user.last_purchase_at and user.images_generated >= 1:
                            response = "🔒 Image generation requires purchase!\n\nImage generation is locked until you make your first purchase. Make a purchase to unlock all image generation features.\n\nUse /buy to get started with credits."
                            send_message(chat_id, response)
                            return
                        
                        # Deduct 10 credits immediately (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, 10)
                        if not success:
                            total = user.credits + user.daily_credits
                            response = f"⚠️ Insufficient credits!\n\nYou have {total} credits but need 10 credits to generate an image.\n\nUse /buy to purchase more credits or /daily to claim free credits."
                            send_message(chat_id, response)
                            return
                        
                        # Store warning to send after successful generation
                        pending_credit_warning = credit_warning
                        
                        db.session.commit()
                        logger.debug(f"10 credits deducted for image (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
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
                    
                    requests.post(f"{BASE_URL}/sendPhoto", json=photo_payload, timeout=TELEGRAM_TIMEOUT)
                    
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
                                
                                # Increment images_generated counter
                                user = User.query.get(user_id)
                                if user:
                                    user.images_generated += 1
                                
                                db.session.commit()
                                logger.debug(f"Image transaction stored synchronously: message_id={message_id}, images_generated={user.images_generated if user else 'N/A'}")
                        except Exception as db_error:
                            logger.error(f"Database error storing image message/transaction: {str(db_error)}")
                            # Flask-SQLAlchemy automatically rolls back on exception within app context
                    
                    # Send credit warning after successful generation
                    if pending_credit_warning:
                        send_message(chat_id, pending_credit_warning)
                    
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
                                user.credits += 10
                                db.session.commit()
                                logger.info(f"Refunded 10 credits due to failed FLUX generation. New balance: {user.credits}")
                    except Exception as db_error:
                        logger.error(f"Database error refunding credits: {str(db_error)}")
                
                send_message(chat_id, f"❌ Image generation failed: {error_msg}\n\n✅ 10 credits have been refunded to your account.")
            
            return
        
        # Check for /qwen command (Qwen-Image text-to-image generation)
        if text.lower().startswith('/qwen '):
            prompt = text[6:].strip()  # Remove '/qwen ' prefix
            
            if not prompt:
                send_message(chat_id, "❌ Please provide a prompt.\n\nExample: /qwen a cyberpunk poster with 'NEON CITY' text")
                return
            
            # OPTIMIZATION: Check balance and deduct credits upfront (before generation)
            pending_credit_warning = None
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        user = User.query.get(user_id)
                        if not user:
                            logger.error(f"User not found for Qwen image generation: {user_id}")
                            send_message(chat_id, "❌ User account not found. Please try /start first.")
                            return
                        
                        # IMAGE GENERATION PAYWALL: Check if user has ever purchased
                        if not user.last_purchase_at and user.images_generated >= 1:
                            response = "🔒 Image generation requires purchase!\n\nImage generation is locked until you make your first purchase. Make a purchase to unlock all image generation features.\n\nUse /buy to get started with credits."
                            send_message(chat_id, response)
                            return
                        
                        # Deduct 8 credits immediately (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, 8)
                        if not success:
                            total = user.credits + user.daily_credits
                            response = f"⚠️ Insufficient credits!\n\nYou have {total} credits but need 8 credits to generate a Qwen image.\n\nUse /buy to purchase more credits or /daily to claim free credits."
                            send_message(chat_id, response)
                            return
                        
                        # Store warning to send after successful generation
                        pending_credit_warning = credit_warning
                        
                        db.session.commit()
                        logger.debug(f"8 credits deducted for Qwen image (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
                except Exception as db_error:
                    logger.error(f"Database error checking/deducting credits: {str(db_error)}")
            
            # Send initial processing message
            status_msg = send_message(chat_id, "🎨 Generating Qwen image...", parse_mode=None)
            
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
                    
                    requests.post(f"{BASE_URL}/sendPhoto", json=photo_payload, timeout=TELEGRAM_TIMEOUT)
                    
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
                                    credits_charged=8
                                )
                                db.session.add(message_record)
                                db.session.commit()
                                message_id = message_record.id
                                logger.info(f"Qwen image message stored synchronously for user {user_id}: {message_id}")
                                
                                # Also store transaction synchronously for reliability
                                transaction = Transaction(
                                    user_id=user_id,
                                    credits_used=8,
                                    message_id=message_id,
                                    transaction_type='qwen_image_generation',
                                    description=f"Qwen image generation: {prompt[:100]}"
                                )
                                db.session.add(transaction)
                                
                                # Increment images_generated counter
                                user = User.query.get(user_id)
                                if user:
                                    user.images_generated += 1
                                
                                db.session.commit()
                                logger.debug(f"Qwen image transaction stored synchronously: message_id={message_id}, images_generated={user.images_generated if user else 'N/A'}")
                        except Exception as db_error:
                            logger.error(f"Database error storing Qwen image message/transaction: {str(db_error)}")
                            # Flask-SQLAlchemy automatically rolls back on exception within app context
                    
                    # Send credit warning after successful generation
                    if pending_credit_warning:
                        send_message(chat_id, pending_credit_warning)
                    
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
                                user.credits += 8
                                db.session.commit()
                                logger.info(f"Refunded 8 credits due to failed Qwen generation. New balance: {user.credits}")
                    except Exception as db_error:
                        logger.error(f"Database error refunding credits: {str(db_error)}")
                
                send_message(chat_id, f"❌ Qwen image generation failed: {error_msg}\n\n✅ 8 credits have been refunded to your account.")
            
            return
        
        # Check for /edit command (Qwen-Image generation - great for image editing and text)
        if text.lower().startswith('/edit '):
            prompt = text[6:].strip()  # Remove '/edit ' prefix
            
            if not prompt:
                send_message(chat_id, "❌ Please provide a prompt.\n\nExample: /edit a cyberpunk poster with 'NEON CITY' text")
                return
            
            # OPTIMIZATION: Check balance and deduct credits upfront (before generation)
            pending_credit_warning = None
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        user = User.query.get(user_id)
                        if not user:
                            logger.error(f"User not found for Qwen image generation: {user_id}")
                            send_message(chat_id, "❌ User account not found. Please try /start first.")
                            return
                        
                        # IMAGE GENERATION PAYWALL: Check if user has ever purchased
                        if not user.last_purchase_at and user.images_generated >= 1:
                            response = "🔒 Image generation requires purchase!\n\nImage generation is locked until you make your first purchase. Make a purchase to unlock all image generation features.\n\nUse /buy to get started with credits."
                            send_message(chat_id, response)
                            return
                        
                        # Deduct 8 credits immediately (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, 8)
                        if not success:
                            total = user.credits + user.daily_credits
                            response = f"⚠️ Insufficient credits!\n\nYou have {total} credits but need 8 credits to generate a Qwen image.\n\nUse /buy to purchase more credits or /daily to claim free credits."
                            send_message(chat_id, response)
                            return
                        
                        # Store warning to send after successful generation
                        pending_credit_warning = credit_warning
                        
                        db.session.commit()
                        logger.debug(f"8 credits deducted for Qwen image (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
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
                    
                    requests.post(f"{BASE_URL}/sendPhoto", json=photo_payload, timeout=TELEGRAM_TIMEOUT)
                    
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
                                
                                # Increment images_generated counter
                                user = User.query.get(user_id)
                                if user:
                                    user.images_generated += 1
                                
                                db.session.commit()
                                logger.debug(f"Qwen image transaction stored synchronously: message_id={message_id}, images_generated={user.images_generated if user else 'N/A'}")
                        except Exception as db_error:
                            logger.error(f"Database error storing Qwen image message/transaction: {str(db_error)}")
                            # Flask-SQLAlchemy automatically rolls back on exception within app context
                    
                    # Send credit warning after successful generation
                    if pending_credit_warning:
                        send_message(chat_id, pending_credit_warning)
                    
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
                                user.credits += 8
                                db.session.commit()
                                logger.info(f"Refunded 8 credits due to failed Qwen generation. New balance: {user.credits}")
                    except Exception as db_error:
                        logger.error(f"Database error refunding credits: {str(db_error)}")
                
                send_message(chat_id, f"❌ Qwen image generation failed: {error_msg}\n\n✅ 8 credits have been refunded to your account.")
            
            return
        
        # Check for /grok command (Grok image generation via xAI)
        if text.lower().startswith('/grok '):
            prompt = text[6:].strip()  # Remove '/grok ' prefix
            
            if not prompt:
                send_message(chat_id, "❌ Please provide a prompt.\n\nExample: /grok a futuristic cityscape at sunset")
                return
            
            # OPTIMIZATION: Check balance and deduct credits upfront (before generation)
            pending_credit_warning = None
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        user = User.query.get(user_id)
                        if not user:
                            logger.error(f"User not found for Grok image generation: {user_id}")
                            send_message(chat_id, "❌ User account not found. Please try /start first.")
                            return
                        
                        # IMAGE GENERATION PAYWALL: Check if user has ever purchased
                        if not user.last_purchase_at and user.images_generated >= 1:
                            response = "🔒 Image generation requires purchase!\n\nImage generation is locked until you make your first purchase. Make a purchase to unlock all image generation features.\n\nUse /buy to get started with credits."
                            send_message(chat_id, response)
                            return
                        
                        # Deduct 8 credits immediately (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, 8)
                        if not success:
                            total = user.credits + user.daily_credits
                            response = f"⚠️ Insufficient credits!\n\nYou have {total} credits but need 8 credits to generate a Grok image.\n\nUse /buy to purchase more credits or /daily to claim free credits."
                            send_message(chat_id, response)
                            return
                        
                        # Store warning to send after successful generation
                        pending_credit_warning = credit_warning
                        
                        db.session.commit()
                        logger.debug(f"8 credits deducted for Grok image (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
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
                    
                    requests.post(f"{BASE_URL}/sendPhoto", json=photo_payload, timeout=TELEGRAM_TIMEOUT)
                    
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
                                
                                # Increment images_generated counter
                                user = User.query.get(user_id)
                                if user:
                                    user.images_generated += 1
                                
                                db.session.commit()
                                logger.debug(f"Grok image transaction stored synchronously: message_id={message_id}, images_generated={user.images_generated if user else 'N/A'}")
                        except Exception as db_error:
                            logger.error(f"Database error storing Grok image message/transaction: {str(db_error)}")
                            # Flask-SQLAlchemy automatically rolls back on exception within app context
                    
                    # Send credit warning after successful generation
                    if pending_credit_warning:
                        send_message(chat_id, pending_credit_warning)
                    
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
                                user.credits += 8
                                db.session.commit()
                                logger.info(f"Refunded 8 credits due to failed Grok generation. New balance: {user.credits}")
                    except Exception as db_error:
                        logger.error(f"Database error refunding credits: {str(db_error)}")
                
                send_message(chat_id, f"❌ Grok image generation failed: {error_msg}\n\n✅ 8 credits have been refunded to your account.")
            
            return
        
        # Check for /uncensored command (Hunyuan-Image-3 generation via Novita AI - fully uncensored)
        if text.lower().startswith('/uncensored '):
            prompt = text[12:].strip()  # Remove '/uncensored ' prefix
            
            if not prompt:
                send_message(chat_id, "❌ Please provide a prompt.\n\nExample: /uncensored a beautiful landscape with mountains")
                return
            
            # OPTIMIZATION: Check balance and deduct credits upfront (before generation)
            pending_credit_warning = None
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        user = User.query.get(user_id)
                        if not user:
                            logger.error(f"User not found for Hunyuan image generation: {user_id}")
                            send_message(chat_id, "❌ User account not found. Please try /start first.")
                            return
                        
                        # IMAGE GENERATION PAYWALL: Check if user has ever purchased
                        if not user.last_purchase_at and user.images_generated >= 1:
                            response = "🔒 Image generation requires purchase!\n\nImage generation is locked until you make your first purchase. Make a purchase to unlock all image generation features.\n\nUse /buy to get started with credits."
                            send_message(chat_id, response)
                            return
                        
                        # Deduct 10 credits immediately (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, 10)
                        if not success:
                            total = user.credits + user.daily_credits
                            response = f"⚠️ Insufficient credits!\n\nYou have {total} credits but need 10 credits to generate an uncensored image.\n\nUse /buy to purchase more credits or /daily to claim free credits."
                            send_message(chat_id, response)
                            return
                        
                        # Store warning to send after successful generation
                        pending_credit_warning = credit_warning
                        
                        db.session.commit()
                        logger.debug(f"10 credits deducted for Hunyuan image (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
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
                    
                    requests.post(f"{BASE_URL}/sendPhoto", json=photo_payload, timeout=TELEGRAM_TIMEOUT)
                    
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
                                
                                # Increment images_generated counter
                                user = User.query.get(user_id)
                                if user:
                                    user.images_generated += 1
                                
                                db.session.commit()
                                logger.debug(f"Hunyuan image transaction stored synchronously: message_id={message_id}, images_generated={user.images_generated if user else 'N/A'}")
                        except Exception as db_error:
                            logger.error(f"Database error storing Hunyuan image message/transaction: {str(db_error)}")
                            # Flask-SQLAlchemy automatically rolls back on exception within app context
                    
                    # Send credit warning after successful generation
                    if pending_credit_warning:
                        send_message(chat_id, pending_credit_warning)
                    
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
                                user.credits += 10
                                db.session.commit()
                                logger.info(f"Refunded 10 credits due to failed Hunyuan generation. New balance: {user.credits}")
                    except Exception as db_error:
                        logger.error(f"Database error refunding credits: {str(db_error)}")
                
                send_message(chat_id, f"❌ Hunyuan image generation failed: {error_msg}\n\n✅ 10 credits have been refunded to your account.")
            
            return
        
        # Check for /vid command (WAN 2.2 video generation - NEW!)
        if photo and caption and caption.lower().startswith('/vid'):
            from llm_api import generate_wan_video, calculate_video_credits
            
            prompt = caption[5:].strip()  # Remove '/vid ' prefix (optional prompt)
            
            logger.info(f"Processing WAN 2.2 video generation request with prompt: {prompt[:50] if prompt else 'No prompt'}...")
            
            # Parse optional parameters from prompt (resolution, duration)
            # Format: /vid 1080P 8s <prompt>  or /vid 8s <prompt> or just /vid <prompt>
            resolution = "720P"  # Default
            duration = 5  # Default
            
            parts = prompt.split(maxsplit=2)
            
            # Check for resolution in first position
            if len(parts) >= 1 and parts[0].upper() in ["480P", "720P", "1080P"]:
                resolution = parts[0].upper()
                parts = parts[1:]  # Remove resolution from parts
                prompt = " ".join(parts)
            
            # Check for duration in first position (after removing resolution if present)
            if len(parts) >= 1 and parts[0].endswith("s") and parts[0][:-1].isdigit():
                duration = int(parts[0][:-1])
                parts = parts[1:]  # Remove duration from parts
                prompt = " ".join(parts)
            
            # Validate resolution/duration combination
            from llm_api import WAN_VIDEO_MODELS
            valid_durations = WAN_VIDEO_MODELS["wan2.2"]["durations"].get(resolution, [])
            if duration not in valid_durations:
                # Format valid durations as human-readable text
                if len(valid_durations) == 1:
                    durations_text = f"{valid_durations[0]}s"
                else:
                    durations_text = " or ".join([f"{d}s" for d in valid_durations])
                
                error_msg = f"❌ Invalid combination: {resolution} only supports {durations_text} duration.\n\n"
                if resolution == "1080P":
                    error_msg += "💡 Tip: 1080P only supports 5s. Use 720P or 480P for 8s videos."
                send_message(chat_id, error_msg)
                return
            
            # Calculate credits based on resolution and duration
            try:
                credits_required = calculate_video_credits("wan2.2", resolution, duration)
            except Exception as calc_error:
                logger.error(f"Credit calculation error: {str(calc_error)}")
                send_message(chat_id, f"❌ Invalid video parameters: {resolution}, {duration}s")
                return
            
            logger.info(f"Video params: resolution={resolution}, duration={duration}s, credits={credits_required}")
            
            # OPTIMIZATION: Check balance and deduct credits upfront (before video generation)
            pending_credit_warning = None
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
                        
                        # Deduct credits immediately (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, credits_required)
                        if not success:
                            total = user.credits + user.daily_credits
                            response = f"⚠️ Insufficient credits!\n\nYou have {total} credits but need {credits_required} credits for video generation ({resolution}, {duration}s).\n\nUse /buy to purchase more credits or /daily to claim free credits."
                            send_message(chat_id, response)
                            return
                        
                        # Store warning to send after successful generation
                        pending_credit_warning = credit_warning
                        
                        db.session.commit()
                        logger.debug(f"{credits_required} credits deducted for WAN 2.2 video (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
                except Exception as db_error:
                    logger.error(f"Database error checking/deducting credits: {str(db_error)}")
            
            # Download the image first
            try:
                photo_file = photo[-1]  # Get largest photo
                file_id = photo_file.get("file_id")
                
                # Get file info
                file_info_response = requests.get(f"{BASE_URL}/getFile?file_id={file_id}", timeout=TELEGRAM_TIMEOUT)
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
                    """Background video generation with comprehensive error handling"""
                    # Send initial message OUTSIDE app context to avoid DB connection issues
                    try:
                        send_message(chat_id, f"🎬 Generating {resolution} {duration}s video from your image... This may take up to 2 minutes.")
                    except Exception as msg_error:
                        logger.error(f"Failed to send initial video generation message: {str(msg_error)}")
                    
                    try:
                        # Call WAN 2.2 video generation API
                        result = generate_wan_video(
                            model_key="wan2.2",
                            image_url=image_url,
                            prompt=prompt,
                            resolution=resolution,
                            duration=duration
                        )
                        
                        if result.get("success"):
                            video_url = result.get("video_url")
                            
                            # PRIORITY 1: Send video to user FIRST
                            try:
                                send_message(chat_id, f"✨ Video generated successfully!\n📹 {resolution}, {duration}s\n\n{video_url}")
                            except Exception as e:
                                logger.error(f"Error sending video message: {str(e)}")
                            
                            # PRIORITY 2: Store to database
                            if DB_AVAILABLE and user_id:
                                try:
                                    with app.app_context():
                                        message_id = store_message(user_id, f"Video ({resolution}, {duration}s): {prompt[:100] if prompt else 'No prompt'}", f"Video: {video_url}", credits_cost=credits_required)
                                        
                                        transaction = Transaction(
                                            user_id=user_id,
                                            credits_used=credits_required,
                                            message_id=message_id,
                                            transaction_type='video_generation',
                                            description=f"WAN 2.2 {resolution} {duration}s: {prompt[:100] if prompt else 'No prompt'}"
                                        )
                                        db.session.add(transaction)
                                        db.session.commit()
                                        logger.debug(f"WAN 2.2 video transaction stored: message_id={message_id}")
                                except Exception as db_error:
                                    logger.error(f"Database error storing video message/transaction (non-critical): {str(db_error)}")
                            
                            # PRIORITY 3: Send credit warning if needed
                            if pending_credit_warning:
                                try:
                                    send_message(chat_id, pending_credit_warning)
                                except:
                                    pass
                        
                        else:
                            error_msg = result.get("error", "Unknown error")
                            
                            # PRIORITY 1: Send error message to user FIRST
                            try:
                                send_message(chat_id, f"❌ Video generation failed: {error_msg}\n\n✅ {credits_required} credits have been refunded to your account.")
                            except Exception as msg_err:
                                logger.error(f"Could not send failure message to user: {str(msg_err)}")
                            
                            # PRIORITY 2: Refund credits
                            if DB_AVAILABLE and user_id:
                                try:
                                    with app.app_context():
                                        user = User.query.get(user_id)
                                        if user:
                                            user.credits += credits_required
                                            db.session.commit()
                                            logger.info(f"Refunded {credits_required} credits due to failed video generation")
                                except Exception as db_error:
                                    logger.error(f"Database error refunding credits (CRITICAL): {str(db_error)}")
                    
                    except Exception as e:
                        # CRITICAL: Catch-all error handler
                        logger.error(f"CRITICAL: WAN 2.2 video generation background thread crashed: {str(e)}", exc_info=True)
                        
                        try:
                            send_message(chat_id, f"❌ An unexpected error occurred during video generation.\n\n✅ {credits_required} credits have been refunded.\n\nError: {str(e)[:100]}")
                        except Exception as notify_err:
                            logger.error(f"Could not send crash notification to user: {str(notify_err)}")
                        
                        # Try to refund credits
                        if DB_AVAILABLE and user_id:
                            try:
                                with app.app_context():
                                    user = User.query.get(user_id)
                                    if user:
                                        user.credits += credits_required
                                        db.session.commit()
                                        logger.info(f"Refunded {credits_required} credits after background thread crash")
                            except Exception as refund_err:
                                logger.error(f"Could not refund credits after crash (CRITICAL): {str(refund_err)}")
                
                # Start background thread
                thread = threading.Thread(target=generate_video_background)
                thread.start()
                
            except Exception as e:
                logger.error(f"Error processing WAN 2.2 video generation request: {str(e)}")
                send_message(chat_id, f"❌ Error: {str(e)}")
            
            return
        
        # Check for /img2video command (WAN 2.5 video generation)
        if photo and caption and caption.lower().startswith('/img2video'):
            prompt = caption[11:].strip()  # Remove '/img2video ' prefix (optional prompt)
            
            logger.info(f"Processing video generation request with prompt: {prompt[:50] if prompt else 'No prompt'}...")
            
            # OPTIMIZATION: Check balance and deduct credits upfront (before video generation)
            pending_credit_warning = None
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
                        
                        # Deduct 50 credits immediately (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, 50)
                        if not success:
                            total = user.credits + user.daily_credits
                            response = f"⚠️ Insufficient credits!\n\nYou have {total} credits but need 50 credits to generate a video.\n\nUse /buy to purchase more credits or /daily to claim free credits."
                            send_message(chat_id, response)
                            return
                        
                        # Store warning to send after successful generation
                        pending_credit_warning = credit_warning
                        
                        db.session.commit()
                        logger.debug(f"50 credits deducted for video generation (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
                except Exception as db_error:
                    logger.error(f"Database error checking/deducting credits: {str(db_error)}")
            
            # Download the image first
            try:
                photo_file = photo[-1]  # Get largest photo
                file_id = photo_file.get("file_id")
                
                # Get file info
                file_info_response = requests.get(f"{BASE_URL}/getFile?file_id={file_id}", timeout=TELEGRAM_TIMEOUT)
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
                    """Background video generation with comprehensive error handling
                    
                    CRITICAL: This function MUST ensure users always get feedback,
                    even if errors occur. Never fail silently.
                    """
                    # Send initial message OUTSIDE app context to avoid DB connection issues
                    try:
                        send_message(chat_id, "🎬 Generating video from your image... This may take up to 2 minutes.")
                    except Exception as msg_error:
                        logger.error(f"Failed to send initial video generation message: {str(msg_error)}")
                    
                    try:
                        # Call video generation API (no database needed here)
                        result = generate_wan25_video(image_url, prompt)
                        
                        if result.get("success"):
                            video_url = result.get("video_url")
                            
                            # PRIORITY 1: Send video to user FIRST (before any database operations)
                            try:
                                send_message(chat_id, f"✨ Video generated successfully!\n\n{video_url}")
                            except Exception as e:
                                logger.error(f"Error sending video message: {str(e)}")
                            
                            # PRIORITY 2: Store to database (non-blocking, errors are logged but don't affect user)
                            if DB_AVAILABLE and user_id:
                                try:
                                    with app.app_context():
                                        message_id = store_message(user_id, f"Video from image: {prompt[:100] if prompt else 'No prompt'}", f"Video: {video_url}", credits_cost=50)
                                        
                                        transaction = Transaction(
                                            user_id=user_id,
                                            credits_used=50,
                                            message_id=message_id,
                                            transaction_type='video_generation',
                                            description=f"Video: {prompt[:100] if prompt else 'No prompt'}"
                                        )
                                        db.session.add(transaction)
                                        db.session.commit()
                                        logger.debug(f"Video transaction stored: message_id={message_id}")
                                except Exception as db_error:
                                    logger.error(f"Database error storing video message/transaction (non-critical): {str(db_error)}")
                                    # Don't fail - user already got their video
                            
                            # PRIORITY 3: Send credit warning if needed
                            if pending_credit_warning:
                                try:
                                    send_message(chat_id, pending_credit_warning)
                                except:
                                    pass
                        
                        else:
                            error_msg = result.get("error", "Unknown error")
                            
                            # PRIORITY 1: Send error message to user FIRST
                            try:
                                send_message(chat_id, f"❌ Video generation failed: {error_msg}\n\n✅ 50 credits have been refunded to your account.")
                            except Exception as msg_err:
                                logger.error(f"Could not send failure message to user: {str(msg_err)}")
                            
                            # PRIORITY 2: Refund credits in database (non-blocking)
                            if DB_AVAILABLE and user_id:
                                try:
                                    with app.app_context():
                                        user = User.query.get(user_id)
                                        if user:
                                            user.credits += 50
                                            db.session.commit()
                                            logger.info(f"Refunded 50 credits due to failed video generation. New balance: {user.credits}")
                                except Exception as db_error:
                                    logger.error(f"Database error refunding credits (CRITICAL - manual fix needed): {str(db_error)}")
                                    # Try to notify user about refund issue
                                    try:
                                        send_message(chat_id, "⚠️ Video failed but we had trouble refunding your credits. Please contact support with this error code: VID_REFUND_FAIL")
                                    except:
                                        pass
                    
                    except Exception as e:
                        # CRITICAL: Catch-all error handler to ensure users always get feedback
                        logger.error(f"CRITICAL: Video generation background thread crashed: {str(e)}", exc_info=True)
                        
                        # PRIORITY 1: Notify user FIRST (before database operations)
                        try:
                            send_message(chat_id, f"❌ An unexpected error occurred during video generation.\n\n✅ 50 credits have been refunded.\n\nError: {str(e)[:100]}\n\nPlease try again or contact support.")
                        except Exception as notify_err:
                            logger.error(f"Could not send crash notification to user: {str(notify_err)}")
                        
                        # PRIORITY 2: Try to refund credits in database
                        if DB_AVAILABLE and user_id:
                            try:
                                with app.app_context():
                                    user = User.query.get(user_id)
                                    if user:
                                        user.credits += 50
                                        db.session.commit()
                                        logger.info(f"Refunded 50 credits after background thread crash")
                            except Exception as refund_err:
                                logger.error(f"Could not refund credits after crash (CRITICAL): {str(refund_err)}")
                                # Try to notify user about refund failure
                                try:
                                    send_message(chat_id, "⚠️ Unexpected error AND trouble refunding credits. Please contact support immediately with error code: VID_CRASH_REFUND_FAIL")
                                except:
                                    pass
                
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
                credits_required = 12
                model_name = "qwen-image-edit"
                status_message = "🎨 Editing with Qwen..."
            else:
                edit_prompt = caption
                credits_required = 15
                model_name = "flux-1-kontext-max-edit"
                status_message = "🎨 Editing with FLUX..."
            
            logger.info(f"Processing {model_name} image editing request: {edit_prompt[:50]}...")
            
            # OPTIMIZATION: Check balance and deduct credits upfront (before editing)
            pending_credit_warning = None
            if DB_AVAILABLE and user_id:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        user = User.query.get(user_id)
                        if not user:
                            logger.error(f"User not found for image editing: {user_id}")
                            send_message(chat_id, "❌ User account not found. Please try /start first.")
                            return
                        
                        # IMAGE EDITING PAYWALL: Check if user has ever purchased
                        if not user.last_purchase_at and user.images_edited >= 1:
                            response = "🔒 Image editing requires purchase!\n\nImage editing is locked until you make your first purchase. Make a purchase to unlock all image editing features.\n\nUse /buy to get started with credits."
                            send_message(chat_id, response)
                            return
                        
                        # Deduct credits immediately (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, credits_required)
                        if not success:
                            total = user.credits + user.daily_credits
                            model_display = "Qwen" if use_qwen else "FLUX"
                            response = f"⚠️ Insufficient credits!\n\nYou have {total} credits but need {credits_required} credits to edit with {model_display}.\n\nUse /buy to purchase more credits or /daily to claim free credits."
                            send_message(chat_id, response)
                            return
                        
                        # Store warning to send after successful editing
                        pending_credit_warning = credit_warning
                        
                        db.session.commit()
                        logger.debug(f"{credits_required} credits deducted for {model_name} editing (daily: {daily_used}, purchased: {purchased_used}). New balance: daily={user.daily_credits}, purchased={user.credits}")
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
                            
                            requests.post(f"{BASE_URL}/sendPhoto", json=photo_payload, timeout=TELEGRAM_TIMEOUT)
                            
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
                                        
                                        # Increment images_edited counter
                                        user = User.query.get(user_id)
                                        if user:
                                            user.images_edited += 1
                                        
                                        db.session.commit()
                                        logger.debug(f"Image edit transaction stored synchronously: message_id={message_id}, images_edited={user.images_edited if user else 'N/A'}")
                                except Exception as db_error:
                                    logger.error(f"Database error storing image edit message/transaction: {str(db_error)}")
                                    # Flask-SQLAlchemy automatically rolls back on exception within app context
                            
                            # Send credit warning after successful editing
                            if pending_credit_warning:
                                send_message(chat_id, pending_credit_warning)
                            
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
        
        # Check for memory commands (! memorize, ! memories, ! forget)
        command_type, command_data = parse_memory_command(text)
        
        if command_type == 'store':
            if DB_AVAILABLE and user:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        memory = store_memory(user.id, command_data, platform='telegram')
                        response = f"✅ Memory saved! (ID: {memory.id})\n\n📝 {command_data}\n\n💡 Use `! memories` to view all saved memories."
                        send_message(chat_id, response, parse_mode="Markdown")
                        return
                except Exception as e:
                    logger.error(f"Failed to store memory: {e}")
                    send_message(chat_id, "❌ Failed to save memory. Please try again.")
                    return
            else:
                send_message(chat_id, "❌ Memory system requires database access.")
                return
        
        elif command_type == 'list':
            if DB_AVAILABLE and user:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        memories = get_user_memories(user.id)
                        response = format_memories_for_display(memories)
                        send_message(chat_id, response, parse_mode="Markdown")
                        return
                except Exception as e:
                    logger.error(f"Failed to list memories: {e}")
                    send_message(chat_id, "❌ Failed to retrieve memories. Please try again.")
                    return
            else:
                send_message(chat_id, "❌ Memory system requires database access.")
                return
        
        elif command_type == 'forget':
            if DB_AVAILABLE and user:
                try:
                    from flask import current_app
                    with current_app.app_context():
                        memory_id = command_data
                        success = delete_memory(user.id, memory_id)
                        if success:
                            response = f"🗑️ Memory [{memory_id}] deleted successfully."
                        else:
                            response = f"❌ Memory [{memory_id}] not found or doesn't belong to you."
                        send_message(chat_id, response)
                        return
                except Exception as e:
                    logger.error(f"Failed to delete memory: {e}")
                    send_message(chat_id, "❌ Failed to delete memory. Please try again.")
                    return
            else:
                send_message(chat_id, "❌ Memory system requires database access.")
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
        selected_model = 'deepseek/deepseek-chat-v3-0324'  # Default model
        
        if DB_AVAILABLE and user_id:
            try:
                from flask import current_app
                with current_app.app_context():
                    # Fetch user and deduct credit immediately (must be synchronous)
                    user = User.query.get(user_id)
                    if user:
                        # Determine credits to deduct based on writing mode or model
                        selected_model = user.preferred_model or 'deepseek/deepseek-chat-v3-0324'
                        # Writing mode always costs 2 credits, otherwise based on model (DeepSeek=1, GPT-4o=3)
                        if writing_mode:
                            credits_to_deduct = 2
                        else:
                            credits_to_deduct = 3 if 'gpt-4o' in selected_model.lower() or 'chatgpt' in selected_model.lower() else 1
                        
                        # Deduct credits (daily credits first, then purchased)
                        success, daily_used, purchased_used, credit_warning = deduct_credits(user, credits_to_deduct)
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

                        if conversation_history:
                            _replace_in_memory_history(chat_id, conversation_history)

                        logger.info(f"Loaded {len(recent_messages)} previous messages for context")
            except Exception as db_error:
                logger.error(f"Error in consolidated DB operations: {str(db_error)}")
                conversation_history = []
                credits_available = True  # Allow response even if DB fails

        if not conversation_history:
            fallback_history = _get_in_memory_history(chat_id)
            if fallback_history:
                conversation_history = fallback_history
                logger.info(f"Using in-memory fallback history for chat {chat_id} ({len(conversation_history)} messages)")

        # If no credits, send error and return
        if not credits_available:
            response = "⚠️ You're out of credits!\n\nTo continue using the bot:\n• Use /daily to claim free credits\n• Or purchase more with /buy"
            send_message(chat_id, response)
            return
        
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
                        edit_message(chat_id, streaming_message_id, display_text, parse_mode="Markdown")
                    else:
                        # Handle continuation message
                        continuation_idx = chunk_idx - 1
                        
                        if continuation_idx < len(continuation_messages):
                            # Update existing continuation message
                            edit_message(chat_id, continuation_messages[continuation_idx], display_text, parse_mode="Markdown")
                        else:
                            # Create new continuation message (without cursor initially)
                            cont_msg = send_message(chat_id, chunk_text, parse_mode="Markdown")
                            if cont_msg and cont_msg.get("ok"):
                                cont_id = cont_msg.get("result", {}).get("message_id")
                                continuation_messages.append(cont_id)
                                # If this is the last chunk, update it with cursor
                                if is_last_chunk:
                                    edit_message(chat_id, cont_id, display_text, parse_mode="Markdown")
            else:
                # Text fits in one message, just update with cursor
                display_text = accumulated_text + " ▌"
                edit_message(chat_id, streaming_message_id, display_text, parse_mode="Markdown")
        
        # Generate response with streaming and progressive updates (include user_id for memory injection and model selection)
        llm_response = generate_response(text, conversation_history, use_streaming=True, update_callback=update_telegram_message, writing_mode=writing_mode, user_id=user_id, model=selected_model)
        
        # Final update with complete response (remove typing indicator and handle continuation)
        if len(llm_response) <= CHUNK_SIZE:
            # Response fits in one message
            if streaming_message_id:
                edit_result = edit_message(chat_id, streaming_message_id, llm_response, parse_mode="Markdown")
                
                # If edit failed, delete placeholder and send new message
                if not edit_result.get("ok"):
                    logger.warning(f"Failed to edit placeholder message {streaming_message_id}, cleaning up and sending new message")
                    delete_message(chat_id, streaming_message_id)
                    send_message(chat_id, llm_response, parse_mode="Markdown")
        else:
            # Split response across multiple messages
            chunks = []
            for i in range(0, len(llm_response), CHUNK_SIZE):
                chunks.append(llm_response[i:i + CHUNK_SIZE])
            
            # Update first message
            if streaming_message_id:
                edit_result = edit_message(chat_id, streaming_message_id, chunks[0], parse_mode="Markdown")
                
                # If edit failed, delete placeholder and send new message
                if not edit_result.get("ok"):
                    logger.warning(f"Failed to edit placeholder message {streaming_message_id}, cleaning up and sending new message")
                    delete_message(chat_id, streaming_message_id)
                    send_message(chat_id, chunks[0], parse_mode="Markdown")
            
            # Send or update continuation messages
            for idx, chunk in enumerate(chunks[1:], start=1):
                if idx - 1 < len(continuation_messages):
                    # Update existing continuation message
                    edit_message(chat_id, continuation_messages[idx - 1], chunk, parse_mode="Markdown")
                else:
                    # Send new continuation message
                    send_message(chat_id, chunk, parse_mode="Markdown")
        
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

        # Update in-memory history fallback for future messages
        _append_in_memory_history(chat_id, "user", text)
        _append_in_memory_history(chat_id, "assistant", llm_response)

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
                        model_used=selected_model,
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
                                description=f"AI message response using {selected_model}"
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
        
    finally:
        # CRITICAL: Always clear processing lock, regardless of success or failure
        # This prevents stuck locks that can last hours/days
        if DB_AVAILABLE and user_id:
            try:
                from flask import current_app
                with current_app.app_context():
                    user = User.query.get(user_id)
                    if user and user.processing_since:
                        lock_duration = (datetime.utcnow() - user.processing_since).total_seconds()
                        user.processing_since = None
                        db.session.commit()
                        logger.debug(f"Rate limit: Cleared processing lock for user {telegram_id} (held for {lock_duration:.2f}s)")
                    elif user:
                        logger.debug(f"Rate limit: No lock to clear for user {telegram_id}")
            except Exception as cleanup_error:
                logger.error(f"Error in finally block clearing processing lock: {cleanup_error}")
