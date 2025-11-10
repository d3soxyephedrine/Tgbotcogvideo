"""
Smart Rate Limiter for Telegram Bot
Allows reflection prompts while preventing spam
"""
import asyncio
import time
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class SmartRateLimiter:
    """
    Intelligent rate limiter that:
    1. Allows reflection prompts to bypass
    2. Queues overflow messages
    3. Prevents concurrent processing abuse
    """
    
    def __init__(self):
        # Track active processing per user
        self.processing_users: Dict[int, datetime] = {}
        
        # Message queue for overflow
        self.message_queue: Dict[int, list] = {}
        
        # Reflection prompt tracking
        self.reflection_in_progress: Dict[int, bool] = {}
        
        # Rate limit settings
        self.max_concurrent_per_user = 1
        self.queue_size_limit = 5
        self.lock_timeout = timedelta(seconds=60)  # Auto-clear stuck locks after 60s
        
    async def acquire_lock(self, user_id: int, is_reflection: bool = False) -> Tuple[bool, str]:
        """
        Try to acquire processing lock for user
        
        Returns:
            (success, status) - status can be 'acquired', 'queued', 'rejected', 'reflection_bypass'
        """
        current_time = datetime.utcnow()
        
        # Clean up stale locks
        self._cleanup_stale_locks(current_time)
        
        # CRITICAL: Reflection prompts get priority bypass
        if is_reflection and user_id in self.reflection_in_progress:
            logger.info(f"Reflection prompt for user {user_id} - bypassing rate limit")
            return True, 'reflection_bypass'
        
        # Check if user is already processing
        if user_id in self.processing_users:
            lock_age = current_time - self.processing_users[user_id]
            
            # If lock is old, clear it
            if lock_age > self.lock_timeout:
                logger.warning(f"Clearing stuck lock for user {user_id} (age: {lock_age})")
                self.release_lock(user_id)
            else:
                # Try to queue the message
                if user_id not in self.message_queue:
                    self.message_queue[user_id] = []
                
                if len(self.message_queue[user_id]) < self.queue_size_limit:
                    self.message_queue[user_id].append({
                        'timestamp': current_time,
                        'queued': True
                    })
                    logger.info(f"Message queued for user {user_id} (queue size: {len(self.message_queue[user_id])})")
                    return False, 'queued'
                else:
                    logger.warning(f"Queue full for user {user_id} - rejecting message")
                    return False, 'rejected'
        
        # Acquire lock
        self.processing_users[user_id] = current_time
        logger.info(f"Lock acquired for user {user_id}")
        return True, 'acquired'
    
    def mark_reflection_start(self, user_id: int):
        """Mark that a reflection prompt is starting"""
        self.reflection_in_progress[user_id] = True
        logger.info(f"Reflection prompt started for user {user_id}")
    
    def mark_reflection_end(self, user_id: int):
        """Mark that a reflection prompt has completed"""
        if user_id in self.reflection_in_progress:
            del self.reflection_in_progress[user_id]
            logger.info(f"Reflection prompt completed for user {user_id}")
    
    def release_lock(self, user_id: int):
        """Release processing lock for user"""
        if user_id in self.processing_users:
            del self.processing_users[user_id]
            logger.info(f"Lock released for user {user_id}")
            
            # Process queued messages if any
            if user_id in self.message_queue and self.message_queue[user_id]:
                queue_size = len(self.message_queue[user_id])
                self.message_queue[user_id].pop(0)  # Remove oldest
                logger.info(f"Processing next queued message for user {user_id} ({queue_size-1} remaining)")
                return True  # Signal that there's a queued message to process
        
        return False
    
    def _cleanup_stale_locks(self, current_time: datetime):
        """Remove locks older than timeout"""
        stale_users = []
        for user_id, lock_time in self.processing_users.items():
            if current_time - lock_time > self.lock_timeout:
                stale_users.append(user_id)
        
        for user_id in stale_users:
            logger.warning(f"Auto-clearing stale lock for user {user_id}")
            del self.processing_users[user_id]
    
    def get_stats(self) -> dict:
        """Get current rate limiter statistics"""
        return {
            'active_locks': len(self.processing_users),
            'queued_messages': sum(len(q) for q in self.message_queue.values()),
            'reflection_prompts': len(self.reflection_in_progress),
            'users_with_locks': list(self.processing_users.keys()),
            'queue_sizes': {uid: len(q) for uid, q in self.message_queue.items() if q}
        }

# Global instance
rate_limiter = SmartRateLimiter()
