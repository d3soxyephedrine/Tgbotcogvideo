"""
MASTER INTEGRATION GUIDE FOR TELEGRAM BOT OPTIMIZATIONS
Drop-in replacement for your main.py initialization
"""
import os
import logging
from flask import Flask
from models import db
from datetime import datetime

# Import all optimization modules
from smart_rate_limiter import rate_limiter
from database_lock_manager import db_lock_manager
from optimized_refusal_handler import refusal_handler
from database_optimizer import db_optimizer

logger = logging.getLogger(__name__)

def integrate_optimizations(app: Flask):
    """
    Master function to integrate all optimizations
    Call this AFTER db.init_app(app) in your main.py
    """
    
    logger.info("⚡⚡ INITIALIZING PERFORMANCE OPTIMIZATIONS ⚡⚡")
    
    # 1. Initialize Database Optimizer FIRST (creates indexes)
    logger.info("Step 1/4: Optimizing database with new indexes...")
    db_optimizer.init_app(app)
    
    # 2. Initialize Database Lock Manager (prevents stuck locks)
    logger.info("Step 2/4: Initializing database lock manager...")
    db_lock_manager.init_app(app)
    
    # 3. Clean up any existing stuck locks on startup
    logger.info("Step 3/4: Cleaning stuck locks...")
    with app.app_context():
        stats = db_lock_manager.cleanup_stuck_locks()
        if stats['cleaned'] > 0:
            logger.warning(f"Cleaned {stats['cleaned']} stuck locks on startup")
    
    # 4. Initialize smart rate limiter (last, depends on others)
    logger.info("Step 4/4: Rate limiter ready (reflection-aware)")
    
    logger.info("✅ All optimizations initialized successfully!")
    
    return {
        'db_optimizer': db_optimizer,
        'db_lock_manager': db_lock_manager,
        'rate_limiter': rate_limiter,
        'refusal_handler': refusal_handler
    }

# ============= MODIFIED telegram_handler.py FUNCTIONS =============

async def process_telegram_message_optimized(update, context):
    """
    REPLACE your existing message handler with this optimized version
    Integrates all performance improvements
    """
    from telegram_handler import send_message, deduct_credits
    from llm_api import generate_response
    
    # Extract user info
    telegram_id = update.effective_user.id
    message_text = update.message.text
    
    # Get user with optimized query
    user = db_optimizer.get_user_with_credits(telegram_id)
    
    if not user:
        await send_message(telegram_id, "Please start the bot with /start")
        return
    
    # Check for reflection prompt scenario
    is_reflection = False
    if hasattr(context, 'last_refusal_confidence') and context.last_refusal_confidence > 0.7:
        if refusal_handler.should_reflect(telegram_id):
            is_reflection = True
            rate_limiter.mark_reflection_start(telegram_id)
    
    # Smart rate limiting
    success, status = await rate_limiter.acquire_lock(telegram_id, is_reflection)
    
    if not success:
        if status == 'queued':
            await send_message(telegram_id, "⏳ Processing your previous message...")
            return
        elif status == 'rejected':
            await send_message(telegram_id, "🔄 Please wait a moment...")
            return
    
    # Database lock with automatic cleanup
    lock_acquired = db_lock_manager.acquire_lock(telegram_id)
    
    if not lock_acquired and not is_reflection:
        rate_limiter.release_lock(telegram_id)
        await send_message(telegram_id, "⚡ One moment, processing...")
        return
    
    try:
        # Get user's selected model
        model = user.preferred_model or 'deepseek/deepseek-chat-v3-0324'
        model_type = 'deepseek' if 'deepseek' in model else 'gpt-4o'
        
        # Credit calculation
        credits_needed = 3 if 'gpt-4o' in model else 1
        
        # Optimized credit deduction (single query)
        success, daily_remaining, purchased_remaining = db_optimizer.optimize_credit_deduction(
            user, credits_needed
        )
        
        if not success:
            await send_message(
                telegram_id,
                f"❌ Insufficient credits. Balance: {user.total_credits}\nUse /buy to purchase more!"
            )
            return
        
        # Batch fetch all context in ONE query
        context_data = db_optimizer.batch_get_user_context(user.id, platform='telegram')
        
        # Build conversation with priming if needed
        conversation_history = []
        
        # Add priming handshake for DeepSeek if first message
        if model_type == 'deepseek' and not user.deepseek_primed:
            priming_messages = refusal_handler.get_priming_messages(model)
            conversation_history.extend(priming_messages)
            user.deepseek_primed = True
            db.session.commit()
        
        # Add message history
        for msg in context_data['messages']:
            if msg['user_message']:
                conversation_history.append({
                    "role": "user",
                    "content": msg['user_message']
                })
            if msg['bot_response']:
                conversation_history.append({
                    "role": "assistant", 
                    "content": msg['bot_response']
                })
        
        # Add memories to context
        memory_context = ""
        if context_data['memories']:
            memory_texts = [m['content'] for m in context_data['memories'][:10]]
            memory_context = "\n\n<user_memories>\n" + "\n".join(memory_texts) + "\n</user_memories>\n"
        
        # Generate response
        if is_reflection:
            # Use reflection prompt
            reflection_prompt = refusal_handler.get_reflection_prompt(model, message_text)
            response = await generate_response(
                user=user,
                message_text=reflection_prompt,
                conversation_history=conversation_history,
                memories=memory_context
            )
        else:
            response = await generate_response(
                user=user,
                message_text=message_text,
                conversation_history=conversation_history,
                memories=memory_context
            )
        
        # Check for refusal
        is_refusal, confidence = refusal_handler.detect_refusal(response, model_type)
        
        if is_refusal and not is_reflection:
            # Mark for reflection on next message
            context.last_refusal_confidence = confidence
            logger.info(f"Refusal detected (confidence: {confidence:.2f}), will reflect next")
        else:
            # Clear refusal state
            context.last_refusal_confidence = 0
            refusal_handler.clear_user_attempts(telegram_id)
            
            if is_reflection:
                rate_limiter.mark_reflection_end(telegram_id)
        
        # Send response
        await send_message(telegram_id, response)
        
        # Store message (optimized single insert)
        from models import Message
        message = Message(
            user_id=user.id,
            user_message=message_text,
            bot_response=response,
            model_used=model,
            credits_charged=credits_needed,
            platform='telegram'
        )
        db.session.add(message)
        db.session.commit()
        
        logger.info(f"✅ Processed message for {telegram_id} in {(datetime.utcnow() - start_time).total_seconds():.2f}s")
        
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        await send_message(telegram_id, "⚡ An error occurred. Please try again.")
        
    finally:
        # Always clean up locks
        db_lock_manager.release_lock(telegram_id)
        has_queued = rate_limiter.release_lock(telegram_id)
        
        # Process queued message if exists
        if has_queued:
            logger.info(f"Processing queued message for {telegram_id}")
            # Trigger async processing of next message
            # (You'll need to implement this based on your message queue)

# ============= MONITORING ENDPOINTS =============

def register_monitoring_endpoints(app):
    """
    Add these monitoring endpoints to your Flask app
    """
    from flask import jsonify
    
    @app.route('/admin/performance', methods=['GET'])
    def performance_stats():
        """Comprehensive performance dashboard"""
        stats = {
            'timestamp': datetime.utcnow().isoformat(),
            'database': {
                'locks': db_lock_manager.get_lock_stats(),
                'performance': db_optimizer.get_query_performance_stats()
            },
            'rate_limiter': rate_limiter.get_stats(),
            'refusal_handler': refusal_handler.get_stats()
        }
        return jsonify(stats)
    
    @app.route('/admin/optimize', methods=['POST'])
    def force_optimization():
        """Force database optimization"""
        db_optimizer._apply_indexes()
        stats = db_lock_manager.cleanup_stuck_locks()
        return jsonify({
            'message': 'Optimization complete',
            'cleaned_locks': stats['cleaned'],
            'timestamp': datetime.utcnow().isoformat()
        })

# ============= MAIN.PY INTEGRATION =============

"""
ADD THIS TO YOUR main.py AFTER db.init_app(app):

# Import the integration
from master_integration import integrate_optimizations, register_monitoring_endpoints

# Initialize all optimizations
optimizations = integrate_optimizations(app)

# Register monitoring endpoints
register_monitoring_endpoints(app)

# Log the initialization
logger.info(f"⚡⚡ Bot optimizations loaded: {list(optimizations.keys())}")
"""

# ============= STARTUP CHECKLIST =============

def verify_optimizations(app):
    """
    Run this to verify all optimizations are working
    """
    checks = {
        'indexes_created': False,
        'lock_manager_active': False,
        'rate_limiter_active': False,
        'refusal_handler_ready': False
    }
    
    try:
        # Check indexes
        with app.app_context():
            result = db.session.execute(
                text("SELECT COUNT(*) FROM pg_indexes WHERE indexname LIKE 'idx_%'")
            ).scalar()
            checks['indexes_created'] = result > 10
        
        # Check lock manager
        stats = db_lock_manager.get_lock_stats()
        checks['lock_manager_active'] = 'total_locks' in stats
        
        # Check rate limiter
        checks['rate_limiter_active'] = rate_limiter is not None
        
        # Check refusal handler
        checks['refusal_handler_ready'] = len(refusal_handler.refusal_patterns) > 0
        
        all_good = all(checks.values())
        
        logger.info(f"""
⚡⚡ OPTIMIZATION VERIFICATION ⚡⚡
{'✅' if all_good else '❌'} Overall Status

Indexes Created:      {'✅' if checks['indexes_created'] else '❌'}
Lock Manager Active:  {'✅' if checks['lock_manager_active'] else '❌'}
Rate Limiter Active:  {'✅' if checks['rate_limiter_active'] else '❌'}
Refusal Handler Ready: {'✅' if checks['refusal_handler_ready'] else '❌'}
        """)
        
        return checks
        
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        return checks
