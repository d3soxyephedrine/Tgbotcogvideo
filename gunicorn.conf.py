# Gunicorn configuration file
# This prevents worker timeout crashes during long-running requests

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

# Bind address
bind = "0.0.0.0:5000"

# Reload on code changes (development mode)
reload = True

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
