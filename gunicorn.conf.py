# Gunicorn configuration file
# This prevents worker timeout crashes during long-running requests
import os

# Worker timeout (5 minutes instead of default 30 seconds)
# This allows time for:
# - LLM streaming responses with reflection prompts (30-60s)
# - Image generation (10-30s)
# - Video generation (30-120s)
timeout = 300

# Number of worker processes
# Using 3 workers allows concurrent request handling
# Prevents one slow request from blocking all traffic
workers = 3

# Bind address - Railway provides PORT env var
port = os.environ.get("PORT", "5000")
bind = f"0.0.0.0:{port}"

# Reload on code changes - DISABLED FOR PRODUCTION STABILITY
# Enabling this causes workers to restart mid-request, losing user data
reload = False

# Reuse port to allow quick restarts
reuse_port = True

# Logging
loglevel = "info"
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr

# Worker class (sync is fine for webhook-based bot)
worker_class = "sync"

# Graceful timeout for workers to finish requests during shutdown
graceful_timeout = 120

# WORKER AUTO-RESTART - Prevents memory leaks and stuck workers
# Restart workers after handling this many requests (prevents memory leaks)
max_requests = 1000
# Add randomness to prevent all workers restarting at once
max_requests_jitter = 100

# Use RAM for worker tmp files (faster than disk)
worker_tmp_dir = "/dev/shm"

# Hook to register Telegram webhook and commands once on master process
# This prevents multiple workers from hitting Telegram API simultaneously (rate limiting)
def on_starting(server):
    """Called just before the master process is initialized"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Master process starting - will register webhook after workers are ready")

def when_ready(server):
    """Called just after the server is started - runs only once on master process

    This is a safety measure - the webhook should have been set by railway_start.sh
    but we register it here as a backup in case:
    1. The startup script webhook registration failed
    2. The Railway domain changed between startup script and server ready
    3. Any other edge cases

    Domain must match the fallback in railway_start.sh and register_telegram_webhook()
    to prevent duplicate registrations with different domains.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Server ready - registering Telegram webhook and commands from master process (safety measure)")

    # Import and call registration functions
    try:
        from main import register_telegram_commands, register_telegram_webhook
        logger.info("Registering Telegram commands...")
        register_telegram_commands()
        logger.info("Registering Telegram webhook (as safety backup)...")
        register_telegram_webhook()
        logger.info("✓ Telegram webhook and commands registered successfully")
    except Exception as e:
        logger.error(f"✗ Error during webhook registration: {str(e)}", exc_info=True)

# Worker lifecycle hooks for monitoring
def worker_int(worker):
    """Called when worker receives INT or QUIT signal"""
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Worker {worker.pid} received INT/QUIT signal - shutting down gracefully")

def worker_abort(worker):
    """Called when worker is aborted (timeout or crash)"""
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"⚠️ WORKER ABORT: Worker {worker.pid} aborted/timed out - will be restarted")

def post_worker_init(worker):
    """Called after a worker has been forked"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"✓ Worker {worker.pid} initialized successfully")

def worker_exit(server, worker):
    """Called when a worker exits"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Worker {worker.pid} exited (normal shutdown)")

def on_exit(server):
    """Called when gunicorn is shutting down"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Gunicorn master process shutting down")
