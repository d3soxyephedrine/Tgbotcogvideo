"""
Database Lock Manager for Telegram Bot
Prevents stuck locks with automatic cleanup and monitoring
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from sqlalchemy import and_
from models import db, User
import logging

logger = logging.getLogger(__name__)

class DatabaseLockManager:
    """
    Manages processing locks at the database level
    with automatic cleanup and health monitoring
    """
    
    def __init__(self, app=None):
        self.app = app
        self.lock_timeout_seconds = 60  # Configurable
        self.cleanup_interval_seconds = 30
        self._cleanup_thread = None
        
    def init_app(self, app):
        """Initialize with Flask app context"""
        self.app = app
        self._start_cleanup_worker()
    
    def acquire_lock(self, user_id: int) -> bool:
        """
        Atomically acquire lock for user
        Uses database transaction for ACID guarantees
        """
        try:
            with self.app.app_context():
                # Use SELECT FOR UPDATE to prevent race conditions
                user = db.session.query(User).filter_by(
                    telegram_id=user_id
                ).with_for_update().first()
                
                if not user:
                    logger.error(f"User {user_id} not found")
                    return False
                
                current_time = datetime.utcnow()
                
                # Check if lock exists and is valid
                if user.processing_since:
                    lock_age = (current_time - user.processing_since).total_seconds()
                    
                    if lock_age < self.lock_timeout_seconds:
                        # Lock is still valid
                        logger.info(f"User {user_id} already has valid lock (age: {lock_age}s)")
                        return False
                    else:
                        # Lock is stale, we can take it
                        logger.warning(f"Overriding stale lock for user {user_id} (age: {lock_age}s)")
                
                # Acquire lock
                user.processing_since = current_time
                db.session.commit()
                logger.info(f"Lock acquired for user {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to acquire lock for user {user_id}: {e}")
            db.session.rollback()
            return False
    
    def release_lock(self, user_id: int) -> bool:
        """
        Release lock for user
        Ensures clean state even on errors
        """
        try:
            with self.app.app_context():
                user = db.session.query(User).filter_by(
                    telegram_id=user_id
                ).first()
                
                if user and user.processing_since:
                    lock_duration = (datetime.utcnow() - user.processing_since).total_seconds()
                    user.processing_since = None
                    db.session.commit()
                    logger.info(f"Lock released for user {user_id} after {lock_duration:.2f}s")
                    
                    # Log warning if lock was held too long
                    if lock_duration > self.lock_timeout_seconds:
                        logger.warning(f"Lock for user {user_id} was held for {lock_duration:.2f}s (timeout: {self.lock_timeout_seconds}s)")
                    
                    return True
                    
                return False
                
        except Exception as e:
            logger.error(f"Failed to release lock for user {user_id}: {e}")
            db.session.rollback()
            return False
    
    def cleanup_stuck_locks(self) -> Dict[str, any]:
        """
        Clean up all stuck locks older than timeout
        Returns statistics about cleaned locks
        """
        stats = {
            'checked': 0,
            'cleaned': 0,
            'failed': 0,
            'stuck_users': []
        }
        
        try:
            with self.app.app_context():
                cutoff_time = datetime.utcnow() - timedelta(seconds=self.lock_timeout_seconds)
                
                # Find all users with stuck locks
                stuck_users = db.session.query(User).filter(
                    and_(
                        User.processing_since != None,
                        User.processing_since < cutoff_time
                    )
                ).all()
                
                stats['checked'] = len(stuck_users)
                
                for user in stuck_users:
                    try:
                        lock_age = (datetime.utcnow() - user.processing_since).total_seconds()
                        logger.warning(f"Cleaning stuck lock for user {user.telegram_id} (age: {lock_age:.2f}s)")
                        
                        user.processing_since = None
                        stats['stuck_users'].append({
                            'user_id': user.telegram_id,
                            'lock_age_seconds': lock_age,
                            'username': user.username
                        })
                        stats['cleaned'] += 1
                        
                    except Exception as e:
                        logger.error(f"Failed to clean lock for user {user.telegram_id}: {e}")
                        stats['failed'] += 1
                
                if stats['cleaned'] > 0:
                    db.session.commit()
                    logger.info(f"Cleaned {stats['cleaned']} stuck locks")
                    
        except Exception as e:
            logger.error(f"Failed to cleanup stuck locks: {e}")
            db.session.rollback()
        
        return stats
    
    def get_lock_stats(self) -> Dict[str, any]:
        """
        Get current lock statistics for monitoring
        """
        try:
            with self.app.app_context():
                current_time = datetime.utcnow()
                cutoff_time = current_time - timedelta(seconds=self.lock_timeout_seconds)
                
                # All users with locks
                all_locked = db.session.query(User).filter(
                    User.processing_since != None
                ).all()
                
                # Stuck locks
                stuck = [u for u in all_locked if u.processing_since < cutoff_time]
                
                # Active (valid) locks
                active = [u for u in all_locked if u.processing_since >= cutoff_time]
                
                stats = {
                    'total_locks': len(all_locked),
                    'active_locks': len(active),
                    'stuck_locks': len(stuck),
                    'oldest_lock_age': None,
                    'average_lock_age': None,
                    'stuck_users': [],
                    'active_users': []
                }
                
                if all_locked:
                    ages = [(current_time - u.processing_since).total_seconds() for u in all_locked]
                    stats['oldest_lock_age'] = max(ages)
                    stats['average_lock_age'] = sum(ages) / len(ages)
                
                for user in stuck:
                    age = (current_time - user.processing_since).total_seconds()
                    stats['stuck_users'].append({
                        'user_id': user.telegram_id,
                        'username': user.username,
                        'lock_age_seconds': age
                    })
                
                for user in active:
                    age = (current_time - user.processing_since).total_seconds()
                    stats['active_users'].append({
                        'user_id': user.telegram_id,
                        'username': user.username,
                        'lock_age_seconds': age
                    })
                
                return stats
                
        except Exception as e:
            logger.error(f"Failed to get lock stats: {e}")
            return {'error': str(e)}
    
    def _start_cleanup_worker(self):
        """
        Start background thread for automatic cleanup
        """
        import threading
        
        def cleanup_worker():
            while True:
                try:
                    time.sleep(self.cleanup_interval_seconds)
                    stats = self.cleanup_stuck_locks()
                    if stats['cleaned'] > 0:
                        logger.info(f"Auto-cleanup: cleared {stats['cleaned']} stuck locks")
                except Exception as e:
                    logger.error(f"Cleanup worker error: {e}")
        
        self._cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        self._cleanup_thread.start()
        logger.info("Started automatic lock cleanup worker")

# Global instance
db_lock_manager = DatabaseLockManager()
