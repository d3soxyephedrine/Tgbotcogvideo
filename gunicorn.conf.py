# Gunicorn configuration file
# Automatically loaded by gunicorn

# Server socket
bind = "0.0.0.0:5000"

# Worker processes
workers = 1
worker_class = "sync"

# Timeout for worker processes (default is 30 seconds, increasing to 120 for LLM streaming)
timeout = 120

# Restart workers when code changes
reload = True

# Reuse port for faster restarts
reuse_port = True

# Logging
loglevel = "info"
accesslog = "-"
errorlog = "-"
