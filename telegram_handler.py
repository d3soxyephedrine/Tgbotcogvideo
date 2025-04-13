import os
import logging
import requests
from llm_api import generate_response, MODEL
from models import db, User, Message
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Get environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_message(chat_id, text):
    """Send a message to a specific chat in Telegram
    
    Args:
        chat_id (int): The ID of the chat to send to
        text (str): The text message to send
    
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
            response = requests.post(
                f"{BASE_URL}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "Markdown"
                }
            )
            responses.append(response.json())
        return responses
    
    # Send a normal message
    try:
        response = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            }
        )
        return response.json()
    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        return {"error": str(e)}

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
        
        # Store user in database if not exists
        from flask import current_app
        with current_app.app_context():
            # Get or create user
            user = User.query.filter_by(telegram_id=telegram_id).first()
            if not user:
                user = User(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name
                )
                db.session.add(user)
                db.session.commit()
                logger.info(f"New user created: {user}")
            
            # Update last interaction
            user.last_interaction = datetime.utcnow()
            db.session.commit()
            
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
                        os.environ['MODEL'] = 'deepseek-ai/deepseek-chat-32b'
                        response = f"Model switched to DeepSeek."
                    else:
                        response = f"Unknown model: {model_name}. Available models: grok, deepseek."
                        
                    # Store command in database
                    message_record = Message(
                        user_id=user.id,
                        user_message=text,
                        bot_response=response,
                        model_used=os.environ.get('MODEL', MODEL)
                    )
                    db.session.add(message_record)
                    db.session.commit()
                    logger.info(f"Model switch command stored: {message_record.id}")
                    
                    # Send response
                    send_message(chat_id, response)
                    return
                else:
                    current_model = os.environ.get('MODEL', MODEL)
                    response = f"Current model: {current_model}\nAvailable models: grok, deepseek\nTo switch, use /model <model_name>"
                    
                    # Store command in database
                    message_record = Message(
                        user_id=user.id,
                        user_message=text,
                        bot_response=response,
                        model_used=current_model
                    )
                    db.session.add(message_record)
                    db.session.commit()
                    
                    # Send response
                    send_message(chat_id, response)
                    return
            
            # Generate response from LLM
            current_model = os.environ.get('MODEL', MODEL)
            llm_response = generate_response(text)
            
            # Store message in database
            message_record = Message(
                user_id=user.id,
                user_message=text,
                bot_response=llm_response,
                model_used=current_model
            )
            db.session.add(message_record)
            db.session.commit()
            logger.info(f"Message stored in database: {message_record.id}")
        
        # Send response back to user
        send_message(chat_id, llm_response)
        
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        error_message = "Sorry, I encountered an error while processing your request. Please try again later."
        send_message(chat_id, error_message)
