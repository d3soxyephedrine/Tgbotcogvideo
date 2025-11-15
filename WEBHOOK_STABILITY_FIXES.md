# Webhook Stability Fixes

## Overview

This document outlines the comprehensive stability improvements made to fix webhook crashes and improve system reliability.

## Issues Identified

### Critical Issues

1. **Database Session Leaks**
   - **Problem**: Database sessions were never cleaned up after request processing
   - **Impact**: Connection pool exhaustion causing webhook to die
   - **Evidence**: 60+ `db.session.commit()` calls but zero `db.session.remove()` calls

2. **Nested App Context Issues**
   - **Problem**: 36+ nested `with current_app.app_context():` blocks
   - **Impact**: Context conflicts, session management issues, memory leaks
   - **Evidence**: Process_update called from app context but created nested contexts

3. **Database Connection Pool Too Small**
   - **Problem**: pool_size=10, max_overflow=20 (30 total) for 3 workers + background threads
   - **Impact**: Connection starvation under load
   - **Evidence**: Workers timing out waiting for database connections

4. **Background Threads Without Cleanup**
   - **Problem**: Webhook spawns daemon threads that don't clean up sessions
   - **Impact**: Sessions leak in background threads
   - **Evidence**: Threading.Thread(daemon=True) without cleanup

5. **Worker Lifecycle Issues**
   - **Problem**: No database cleanup on worker exit/crash
   - **Impact**: Connections remain open when workers restart
   - **Evidence**: Missing cleanup in gunicorn lifecycle hooks

### Secondary Issues

6. **Missing Monitoring**
   - **Problem**: No health check endpoint to detect issues
   - **Impact**: Can't monitor webhook health or debug crashes
   - **Evidence**: No health endpoints defined

7. **Limited Crash Diagnostics**
   - **Problem**: Worker crashes don't log stack traces
   - **Impact**: Difficult to debug root causes
   - **Evidence**: Basic worker_abort logging only

## Fixes Implemented

### 1. Database Session Cleanup (telegram_handler.py)

**Changed**: Added session cleanup wrapper to `process_update()`

```python
def process_update(update):
    """Process an update from Telegram

    CRITICAL: This function MUST be called from within a Flask app context.
    It will clean up database sessions when done to prevent connection pool exhaustion.
    """
    try:
        # Handle pre-checkout query, successful payment, etc.
        _process_update_impl(update)
    finally:
        # CRITICAL: Always clean up database session
        if DB_AVAILABLE:
            try:
                db.session.remove()
                logger.debug("Database session cleaned up successfully")
            except Exception as cleanup_error:
                logger.error(f"Error cleaning up database session: {str(cleanup_error)}")
```

**Impact**: Sessions are now ALWAYS cleaned up, preventing connection pool exhaustion

### 2. Removed Nested App Contexts (telegram_handler.py)

**Changed**: Removed all 36 nested `with current_app.app_context():` blocks

**Before**:
```python
if DB_AVAILABLE:
    try:
        from flask import current_app
        with current_app.app_context():  # NESTED - BAD
            user = User.query.filter_by(telegram_id=telegram_id).first()
            # ...
```

**After**:
```python
if DB_AVAILABLE:
    try:
        # Already in app context from webhook handler - no nesting needed
        user = User.query.filter_by(telegram_id=telegram_id).first()
        # ...
```

**Impact**: Eliminates context conflicts and improves session management

### 3. Increased Database Connection Pool (main.py)

**Changed**: Increased pool size for 3 workers + background threads

```python
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,  # Recycle connections after 5 minutes
    "pool_pre_ping": True,  # Verify connections before use
    "pool_size": 15,  # Base pool size (was 10)
    "max_overflow": 30,  # Additional connections (was 20)
    "pool_timeout": 30,  # Timeout waiting for connection
    # ...
}
```

**Impact**:
- Old: 10 + 20 = 30 total connections
- New: 15 + 30 = 45 total connections
- ~15 connections per worker (45/3) is sufficient for background processing

### 4. Added Health Check Endpoint (main.py)

**Added**: `/health` endpoint with comprehensive monitoring

```python
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring webhook stability"""
    # Returns:
    # - Overall status (healthy/degraded/unhealthy)
    # - Database connectivity
    # - Webhook registration status
    # - Database pool statistics
    # - Environment configuration
```

**Features**:
- Database connection test with pool statistics
- Telegram webhook status check
- Pending update count monitoring
- Returns HTTP 503 if unhealthy (for load balancer integration)

**Usage**:
```bash
curl https://your-domain.com/health
```

### 5. Enhanced Worker Lifecycle Management (gunicorn.conf.py)

**Added**: Database cleanup on worker initialization, exit, and crash

```python
def post_worker_init(worker):
    """Clean up inherited database connections from parent process"""
    from main import app, db
    with app.app_context():
        db.engine.dispose()

def worker_exit(server, worker):
    """Clean up database connections on worker exit"""
    from main import app, db
    with app.app_context():
        db.session.remove()
        db.engine.dispose()

def worker_abort(worker):
    """Enhanced crash logging with stack traces"""
    # Logs worker age, tmp directory, and thread stack traces
```

**Impact**: Connections are properly released when workers restart or crash

### 6. Enhanced Crash Diagnostics (gunicorn.conf.py)

**Added**: Stack trace logging on worker crashes

```python
def worker_abort(worker):
    """Enhanced logging for debugging worker crashes"""
    logger.error(f"⚠️ WORKER ABORT: Worker {worker.pid} aborted/timed out")
    logger.error(f"Worker age: {worker.age}s")

    # Log stack traces for all threads
    for thread_id, frame in sys._current_frames().items():
        logger.error(f"Thread {thread_id} stack trace:")
        logger.error(''.join(traceback.format_stack(frame)))
```

**Impact**: Better debugging information when crashes occur

### 7. Added Rollback on Database Errors (telegram_handler.py)

**Changed**: Added `db.session.rollback()` on database exceptions

```python
except Exception as db_error:
    logger.error(f"❌ Database error: {str(db_error)}", exc_info=True)
    db.session.rollback()  # Rollback failed transaction
    user_id = None
```

**Impact**: Prevents stuck transactions from blocking other operations

## Files Modified

1. **telegram_handler.py** (Major changes)
   - Added session cleanup wrapper
   - Removed 36 nested app_context blocks
   - Added rollback on errors

2. **main.py** (Medium changes)
   - Increased database pool size
   - Added /health endpoint

3. **gunicorn.conf.py** (Medium changes)
   - Enhanced worker lifecycle hooks
   - Added database cleanup on worker events
   - Improved crash diagnostics

## Testing

### Manual Testing

1. **Health Check**:
   ```bash
   curl https://your-domain.com/health
   ```

2. **Database Pool Monitoring**:
   - Monitor pool statistics in health check response
   - Check for connection leaks over time

3. **Worker Restart Testing**:
   - Monitor logs for clean worker exits
   - Verify database connections are released

### Load Testing

1. Send multiple concurrent messages to bot
2. Monitor database pool statistics in /health endpoint
3. Verify connections don't exceed pool limits
4. Check logs for session cleanup messages

## Deployment

These changes are backward compatible and safe to deploy immediately.

### Expected Improvements

1. **Stability**: Webhook should no longer die from connection pool exhaustion
2. **Performance**: Better connection reuse, less overhead from context switching
3. **Monitoring**: Health endpoint provides visibility into system state
4. **Debugging**: Enhanced crash logs help diagnose future issues

### Monitoring After Deployment

1. Check `/health` endpoint regularly
2. Monitor `db.session.remove()` in logs to verify cleanup
3. Watch database pool statistics for leaks
4. Monitor worker restart frequency

## Rollback Plan

If issues occur, revert by:
```bash
git revert <commit-hash>
git push -u origin <branch>
```

## Additional Recommendations

1. **Set up external monitoring** on `/health` endpoint (e.g., UptimeRobot)
2. **Configure Railway health checks** to use `/health` endpoint
3. **Monitor database connection metrics** in production
4. **Set up alerts** for unhealthy status (HTTP 503)
5. **Review logs** for session cleanup messages to verify fixes

## Summary

These fixes address the root causes of webhook instability:
- ✅ Database session leaks FIXED (session cleanup wrapper)
- ✅ Nested app contexts FIXED (removed all 36 instances)
- ✅ Connection pool exhaustion FIXED (increased from 30 to 45)
- ✅ Worker lifecycle issues FIXED (cleanup on init/exit/crash)
- ✅ Monitoring ADDED (health check endpoint)
- ✅ Crash diagnostics IMPROVED (stack traces on abort)

The webhook should now run stably with proper resource cleanup and monitoring.
