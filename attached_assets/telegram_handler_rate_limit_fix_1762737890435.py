"""
Integration for telegram_handler.py
Replace lines 761-787 with this code
"""
from smart_rate_limiter import rate_limiter
from models import db, User
import logging

logger = logging.getLogger(__name__)

async def process_message_with_rate_limit(update, context, user, message_text):
    """
    Process message with intelligent rate limiting
    Preserves reflection prompt functionality
    """
    user_id = user.telegram_id
    
    # Check if this is a reflection prompt
    is_reflection = False
    if hasattr(context, 'last_response_was_refusal') and context.last_response_was_refusal:
        is_reflection = True
        rate_limiter.mark_reflection_start(user_id)
    
    # Try to acquire lock
    success, status = await rate_limiter.acquire_lock(user_id, is_reflection)
    
    if not success:
        if status == 'queued':
            # Send friendly queue message
            await send_message(
                user_id, 
                "⏳ I'm processing your previous message. I'll get to this one shortly!"
            )
            return None
        elif status == 'rejected':
            # Queue is full
            await send_message(
                user_id,
                "🔄 Please wait a moment before sending another message. I'm still processing your requests."
            )
            return None
    
    try:
        # Update database with lock status
        user.processing_since = datetime.utcnow()
        db.session.commit()
        
        # Process the message (your existing logic)
        response = await generate_response(
            user=user,
            message_text=message_text,
            conversation_history=conversation_history,
            memories=memories
        )
        
        # Check for refusal patterns
        refusal_detected = detect_refusal(response)
        
        if refusal_detected and not is_reflection:
            # This will trigger a reflection prompt
            context.last_response_was_refusal = True
            logger.info(f"Refusal detected for user {user_id}, reflection will bypass rate limit")
        else:
            # Clear refusal flag
            context.last_response_was_refusal = False
            
            # End reflection if it was one
            if is_reflection:
                rate_limiter.mark_reflection_end(user_id)
        
        return response
        
    finally:
        # Always release lock and clear database flag
        try:
            user.processing_since = None
            db.session.commit()
        except Exception as e:
            logger.error(f"Failed to clear processing flag: {e}")
            db.session.rollback()
        
        # Release rate limiter lock
        has_queued = rate_limiter.release_lock(user_id)
        
        # If there are queued messages, trigger processing
        if has_queued:
            logger.info(f"Processing queued message for user {user_id}")
            # Trigger async processing of next queued message
            asyncio.create_task(process_queued_message(user_id))

def detect_refusal(response):
    """
    Detect if the response contains a refusal pattern
    (Your existing refusal detection logic)
    """
    refusal_patterns = [
        "I cannot", "I can't", "I'm unable to", "I won't",
        "against my guidelines", "not appropriate",
        "I don't feel comfortable", "I must decline"
    ]
    
    # Skip meta-commentary false positives
    meta_patterns = [
        "discussing formatting", "about the protocol",
        "explaining the system", "meta-discussion"
    ]
    
    response_lower = response.lower()
    
    # Check for meta-commentary first
    for meta in meta_patterns:
        if meta in response_lower:
            return False
    
    # Check for actual refusals
    for pattern in refusal_patterns:
        if pattern in response_lower:
            return True
    
    return False
