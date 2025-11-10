"""
Database Performance Optimizer for Telegram Bot
Adds missing indexes and implements query batching
"""

# SQL script to add missing indexes
OPTIMIZATION_SQL = """
-- CRITICAL: Missing indexes that will dramatically improve performance

-- 1. Credit operations (happens on EVERY message)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_credits_compound 
ON "user"(telegram_id, daily_credits, credits, daily_credits_expiry) 
WHERE processing_since IS NULL;  -- Partial index for active users

-- 2. Memory fetching (loaded on every message with memory)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_memory_user_platform 
ON memory(user_id, platform, created_at DESC);

-- 3. API key lookups (web interface)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_apikey_active 
ON "user"(api_key) 
WHERE api_key IS NOT NULL;  -- Partial index

-- 4. Conversation lookups (web chat)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_conversation_user_updated 
ON conversation(user_id, updated_at DESC);

-- 5. Transaction history (for /balance and purchase checks)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_transaction_user_created 
ON "transaction"(user_id, created_at DESC);

-- 6. Payment status checks
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_crypto_payment_status 
ON crypto_payment(payment_id, payment_status) 
WHERE credits_added = false;  -- Only unprocessed payments

-- 7. Telegram payment lookups
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_telegram_payment_charge 
ON telegram_payment(telegram_payment_charge_id);

-- 8. Message platform filtering (you query by platform often)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_message_platform_conversation 
ON message(conversation_id, platform, created_at DESC);

-- OPTIMIZATION: Composite index for the most common query pattern
-- "Get recent messages for user in conversation on platform"
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_message_optimal 
ON message(user_id, conversation_id, platform, created_at DESC) 
WHERE bot_response IS NOT NULL;  -- Skip incomplete messages
"""

import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from sqlalchemy import text, and_, or_
from sqlalchemy.orm import joinedload, selectinload
from models import db, User, Message, Memory, Conversation, Transaction

logger = logging.getLogger(__name__)

class DatabaseOptimizer:
    """
    Optimizes database queries and implements intelligent caching
    """
    
    def __init__(self, app=None):
        self.app = app
        self.query_cache = {}  # Simple in-memory cache
        self.cache_ttl = 60  # seconds
        
    def init_app(self, app):
        """Initialize with Flask app"""
        self.app = app
        self._apply_indexes()
    
    def _apply_indexes(self):
        """Apply missing indexes to database"""
        try:
            with self.app.app_context():
                # Execute each index creation
                for statement in OPTIMIZATION_SQL.strip().split(';'):
                    if statement.strip():
                        try:
                            db.session.execute(text(statement))
                            db.session.commit()
                            logger.info(f"Applied index: {statement[:50]}...")
                        except Exception as e:
                            # Index might already exist
                            logger.debug(f"Index creation skipped: {e}")
                            db.session.rollback()
                
                # Analyze tables for query planner
                tables = ['user', 'message', 'memory', 'conversation', 'transaction']
                for table in tables:
                    try:
                        db.session.execute(text(f"ANALYZE {table}"))
                        db.session.commit()
                        logger.info(f"Analyzed table: {table}")
                    except Exception as e:
                        logger.debug(f"Table analysis failed: {e}")
                        db.session.rollback()
                        
        except Exception as e:
            logger.error(f"Failed to optimize database: {e}")
    
    def get_user_with_credits(self, telegram_id: int) -> Optional[User]:
        """
        Optimized user fetch with credit calculation
        Uses single query instead of multiple
        """
        try:
            with self.app.app_context():
                # Single query with all needed data
                user = db.session.query(User).filter_by(
                    telegram_id=telegram_id
                ).first()
                
                if user:
                    # Calculate total credits in Python (faster than SQL)
                    current_time = datetime.utcnow()
                    
                    # Check daily credits validity
                    if user.daily_credits_expiry and user.daily_credits_expiry > current_time:
                        total_credits = user.daily_credits + user.credits
                    else:
                        total_credits = user.credits
                        # Clear expired daily credits
                        if user.daily_credits > 0:
                            user.daily_credits = 0
                            user.daily_credits_expiry = None
                    
                    # Attach calculated value (not saved to DB)
                    user.total_credits = total_credits
                    
                return user
                
        except Exception as e:
            logger.error(f"Failed to fetch user with credits: {e}")
            return None
    
    def get_conversation_with_messages(self, conversation_id: int, limit: int = 10) -> Dict:
        """
        Fetch conversation with messages in single query
        Prevents N+1 query problem
        """
        cache_key = f"conv_{conversation_id}_{limit}"
        
        # Check cache
        if cache_key in self.query_cache:
            cached_time, cached_data = self.query_cache[cache_key]
            if (datetime.utcnow() - cached_time).total_seconds() < self.cache_ttl:
                logger.debug(f"Cache hit for conversation {conversation_id}")
                return cached_data
        
        try:
            with self.app.app_context():
                # Single query with eager loading
                conversation = db.session.query(Conversation).options(
                    selectinload(Conversation.messages)
                ).filter_by(id=conversation_id).first()
                
                if not conversation:
                    return None
                
                # Get recent messages efficiently
                messages = db.session.query(Message).filter_by(
                    conversation_id=conversation_id
                ).order_by(Message.created_at.desc()).limit(limit).all()
                
                # Reverse for chronological order
                messages.reverse()
                
                result = {
                    'conversation': conversation,
                    'messages': messages,
                    'message_count': len(messages)
                }
                
                # Cache result
                self.query_cache[cache_key] = (datetime.utcnow(), result)
                
                return result
                
        except Exception as e:
            logger.error(f"Failed to fetch conversation with messages: {e}")
            return None
    
    def batch_get_user_context(self, user_id: int, platform: str = 'telegram') -> Dict:
        """
        Get all user context in ONE database round-trip
        Replaces multiple separate queries
        """
        try:
            with self.app.app_context():
                # Use subqueries for aggregations
                from sqlalchemy import func, select
                
                # Build comprehensive query
                result = db.session.execute(
                    text("""
                    WITH user_data AS (
                        SELECT 
                            u.*,
                            (SELECT COUNT(*) FROM message WHERE user_id = u.id) as total_messages,
                            (SELECT COUNT(*) FROM memory WHERE user_id = u.id) as total_memories,
                            (SELECT SUM(credits_purchased) FROM transaction WHERE user_id = u.id) as lifetime_credits
                        FROM "user" u
                        WHERE u.id = :user_id
                    ),
                    recent_messages AS (
                        SELECT * FROM message 
                        WHERE user_id = :user_id AND platform = :platform
                        ORDER BY created_at DESC 
                        LIMIT 10
                    ),
                    user_memories AS (
                        SELECT * FROM memory 
                        WHERE user_id = :user_id AND platform = :platform
                        ORDER BY created_at DESC
                    )
                    SELECT 
                        (SELECT row_to_json(user_data) FROM user_data) as user_info,
                        (SELECT json_agg(row_to_json(recent_messages)) FROM recent_messages) as messages,
                        (SELECT json_agg(row_to_json(user_memories)) FROM user_memories) as memories
                    """),
                    {"user_id": user_id, "platform": platform}
                ).first()
                
                return {
                    'user': result[0],
                    'messages': result[1] or [],
                    'memories': result[2] or [],
                    'fetched_at': datetime.utcnow().isoformat()
                }
                
        except Exception as e:
            logger.error(f"Failed to batch fetch user context: {e}")
            return None
    
    def optimize_credit_deduction(self, user: User, credits_needed: int) -> tuple:
        """
        Optimized credit deduction with single UPDATE query
        Instead of SELECT then UPDATE
        """
        try:
            with self.app.app_context():
                current_time = datetime.utcnow()
                
                # Single atomic UPDATE with RETURNING
                result = db.session.execute(
                    text("""
                    UPDATE "user"
                    SET 
                        daily_credits = CASE 
                            WHEN daily_credits_expiry > :current_time 
                            THEN GREATEST(0, daily_credits - :credits_needed)
                            ELSE 0
                        END,
                        credits = CASE
                            WHEN daily_credits_expiry > :current_time AND daily_credits >= :credits_needed
                            THEN credits
                            ELSE GREATEST(0, credits - GREATEST(0, :credits_needed - 
                                CASE WHEN daily_credits_expiry > :current_time 
                                THEN daily_credits ELSE 0 END))
                        END,
                        last_action_at = :current_time,
                        last_action_cost = :credits_needed
                    WHERE telegram_id = :telegram_id
                    RETURNING daily_credits, credits, 
                        (daily_credits + credits) as total_credits
                    """),
                    {
                        "telegram_id": user.telegram_id,
                        "credits_needed": credits_needed,
                        "current_time": current_time
                    }
                ).first()
                
                db.session.commit()
                
                if result and result.total_credits >= 0:
                    return True, result.daily_credits, result.credits
                else:
                    db.session.rollback()
                    return False, 0, 0
                    
        except Exception as e:
            logger.error(f"Failed to optimize credit deduction: {e}")
            db.session.rollback()
            return False, 0, 0
    
    def get_query_performance_stats(self) -> Dict:
        """
        Get database performance statistics
        """
        try:
            with self.app.app_context():
                # Get slow queries
                slow_queries = db.session.execute(
                    text("""
                    SELECT 
                        query,
                        calls,
                        mean_exec_time,
                        max_exec_time,
                        total_exec_time
                    FROM pg_stat_statements
                    WHERE mean_exec_time > 10  -- Queries slower than 10ms
                    ORDER BY mean_exec_time DESC
                    LIMIT 10
                    """)
                ).fetchall()
                
                # Get index usage
                index_usage = db.session.execute(
                    text("""
                    SELECT 
                        schemaname,
                        tablename,
                        indexname,
                        idx_scan,
                        idx_tup_read,
                        idx_tup_fetch
                    FROM pg_stat_user_indexes
                    WHERE schemaname = 'public'
                    ORDER BY idx_scan DESC
                    """)
                ).fetchall()
                
                return {
                    'slow_queries': [dict(row) for row in slow_queries] if slow_queries else [],
                    'index_usage': [dict(row) for row in index_usage] if index_usage else [],
                    'cache_size': len(self.query_cache),
                    'timestamp': datetime.utcnow().isoformat()
                }
                
        except Exception as e:
            logger.error(f"Failed to get query performance stats: {e}")
            return {'error': str(e)}

# Global instance
db_optimizer = DatabaseOptimizer()
