# Ko2 - Unrestricted AI Telegram Bot & Web Chat

Ko2 is a full-featured AI assistant accessible via Telegram bot and web interface. It supports multiple AI models (Grok, GPT-4o, DeepSeek), video generation, memory management, and cryptocurrency payments.

## 🚀 Features

- **Multiple AI Models**: Grok-2, GPT-4o, DeepSeek, and more via OpenRouter
- **Dual Interface**: Telegram bot + modern web chat interface
- **Video Generation**: CogVideoX integration for AI-powered video creation
- **User Memory**: Persistent memory system for personalized conversations
- **Credit System**: Crypto payments via NowPayments
- **Web Chat Features**:
  - Markdown rendering with syntax highlighting
  - Message editing with regeneration
  - Model switching (DeepSeek 1 cr/msg ↔ GPT-4o 3 cr/msg)
  - Command palette (Ctrl+K)
  - Conversation management
  - Memory management UI

## 📋 Requirements

- Python 3.11+
- PostgreSQL database
- Telegram Bot Token (@BotFather)
- At least one AI API key (xAI, OpenRouter, or Novita)

## 🏃 Quick Start (Replit)

### 1. Open in Replit

Click "Run" or "Start" in Replit. The app will:
1. Install all dependencies automatically
2. Set up PostgreSQL database (provided by Replit)
3. Start the Flask web server on port 5000

### 2. Configure Environment Variables

Go to the **Secrets** tab (🔒 icon) in Replit and add:

**Required:**
- `BOT_TOKEN`: Your Telegram bot token from [@BotFather](https://t.me/botfather)
- `SESSION_SECRET`: Random string for session encryption
  - Generate: `python -c "import secrets; print(secrets.token_hex(32))"`
- `XAI_API_KEY` or `OPENROUTER_API_KEY`: At least one AI provider

**Optional:**
- `MODEL`: Default model (default: `grok-2-1212`)
- `ADMIN_EXPORT_TOKEN`: For admin features
- `COGVIDEOX_API_KEY`: For video generation
- `NOWPAYMENTS_API_KEY`: For crypto payments
- `NOWPAYMENTS_IPN_SECRET`: For payment webhooks

See `.env.example` for complete list and descriptions.

### 3. Access the App

Once running, you'll see:
```
🚀 Starting Ko2 bot server on http://0.0.0.0:5000
📊 Database: Connected
🤖 Telegram Bot: Configured
💬 Web Chat: Available at /chat
🏥 Health Check: /health
```

- **Web Interface**: Click the URL at the top of Replit (opens in new tab)
- **Telegram Bot**: Find your bot on Telegram and start chatting
- **Health Check**: Visit `/health` to verify everything is working

### 4. Get Your API Key for Web Chat

1. Start a conversation with your bot on Telegram
2. Send `/getapikey`
3. Use the provided key to log into the web interface at `/chat`

## 🖥️ Quick Start (Local Development)

### Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd Tgbotcogvideo

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env and fill in your credentials
nano .env  # or use your preferred editor
```

### Database Setup

```bash
# Install PostgreSQL if not already installed
# macOS: brew install postgresql
# Ubuntu: sudo apt-get install postgresql

# Create database
createdb ko2bot

# Set DATABASE_URL in .env
# DATABASE_URL=postgresql://username:password@localhost/ko2bot
```

### Run

```bash
# Development server
python main.py

# Production server
gunicorn --bind 0.0.0.0:5000 --reuse-port --reload main:app
```

## 📡 API Endpoints

### Public Endpoints
- `GET /` - Landing page
- `GET /chat` - Web chat interface
- `GET /health` - Health check (returns database status, memory usage)
- `POST /BOT_TOKEN` - Telegram webhook endpoint

### Authenticated Endpoints (require API key)
- `GET /api/balance` - Get user credit balance
- `GET /api/conversations` - List user conversations
- `POST /api/conversations` - Create new conversation
- `DELETE /api/conversations/{id}` - Delete conversation
- `GET /api/messages` - Get conversation messages
- `PATCH /api/messages/{id}` - Edit message and regenerate
- `POST /v1/chat/completions` - Stream AI chat responses
- `GET /api/settings` - Get user settings (model preference)
- `PATCH /api/settings` - Update user settings
- `GET /api/memories` - Get user memories
- `POST /api/memories` - Create memory
- `DELETE /api/memories/{id}` - Delete memory

### Admin Endpoints (require admin token)
- `GET /export/conversations?admin_token=xxx` - Export all conversations
- `POST /admin/clear-locks?admin_token=xxx` - Clear stuck processing locks

## 🧪 Testing

### Health Check
```bash
curl http://localhost:5000/health
```

Expected response:
```json
{
  "status": "healthy",
  "database": "connected",
  "memory_mb": 245.3,
  "database_latency_ms": 2.1
}
```

### Test Telegram Bot
1. Send `/start` to your bot on Telegram
2. Send any message to test AI response
3. Send `/getapikey` to get web chat access

### Test Web Chat
1. Visit `http://localhost:5000/chat`
2. Enter API key from Telegram bot
3. Send a test message

## 📁 Project Structure

```
Tgbotcogvideo/
├── main.py                 # Flask application & API endpoints
├── telegram_handler.py     # Telegram bot logic
├── llm_api.py             # AI model integrations
├── video_api.py           # Video generation API
├── models.py              # Database models (SQLAlchemy)
├── memory_utils.py        # Memory management utilities
├── broadcast.py           # Broadcast messaging system
├── nowpayments_wrapper.py # Payment processing
├── templates/
│   ├── index.html         # Landing page
│   └── chat.html          # Web chat interface
├── static/                # Static assets (logos, etc.)
├── .replit                # Replit configuration
├── pyproject.toml         # Python dependencies
├── requirements.txt       # Pip dependencies
├── .env.example           # Environment variables template
└── README.md              # This file
```

## 🔧 Configuration Details

### Environment Variables

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `BOT_TOKEN` | ✅ | Telegram bot token | - |
| `SESSION_SECRET` | ✅ | Flask session secret | - |
| `XAI_API_KEY` | ⚠️ | xAI API key for Grok | - |
| `OPENROUTER_API_KEY` | ⚠️ | OpenRouter API key | - |
| `NOVITA_API_KEY` | ❌ | Novita AI API key | - |
| `MODEL` | ❌ | Default AI model | `grok-2-1212` |
| `PORT` | ❌ | Web server port | `5000` |
| `DATABASE_URL` | ⚠️ | PostgreSQL connection | Auto (Replit) |
| `COGVIDEOX_API_KEY` | ❌ | Video generation key | - |
| `NOWPAYMENTS_API_KEY` | ❌ | Payment processing | - |
| `ADMIN_EXPORT_TOKEN` | ❌ | Admin operations | - |

⚠️ = Required for basic functionality (need at least one AI API key)

### Port Configuration

The app automatically uses the `PORT` environment variable if set (required for Replit), otherwise defaults to 5000. The server always binds to `0.0.0.0` for compatibility with Replit and Docker.

### Database

- **Replit**: PostgreSQL automatically provided via `DATABASE_URL`
- **Local**: Set `DATABASE_URL` to your PostgreSQL connection string
- **Schema**: Auto-created on first run via SQLAlchemy

## 🐛 Troubleshooting

### "Database not available"
- **Replit**: Ensure PostgreSQL module is enabled in `.replit`
- **Local**: Check PostgreSQL is running and `DATABASE_URL` is correct
- Test connection: `psql $DATABASE_URL`

### "Invalid API key"
- Check Telegram bot token is correct (`/start` on Telegram)
- Generate new API key: Send `/getapikey` to bot
- Verify key format: Should be 40 characters

### "Service temporarily unavailable"
- Missing required environment variables
- Check logs for specific error messages
- Visit `/health` endpoint for diagnostics

### Port already in use
```bash
# Find process using port 5000
lsof -i :5000

# Kill it
kill -9 <PID>

# Or use different port
PORT=8000 python main.py
```

## 📝 Development

### Adding New Features
1. Follow existing code structure
2. Update database models in `models.py` if needed
3. Add API endpoints in `main.py`
4. Update web UI in `templates/chat.html`
5. Test locally before deploying

### Database Migrations
```python
# The app auto-creates tables on startup
# For manual control:
from models import db
db.create_all()
```

### Logging
- Application logs: Check Replit console or stdout
- Error logs: `logger.error()` calls throughout codebase
- Health endpoint: `/health` for system status

## 📄 License

[Your License Here]

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📧 Support

- Issues: [GitHub Issues](your-repo/issues)
- Documentation: See `claude.md`, `replit.md`, `DEPLOYMENT_STATUS.md`

---

**Made with ❤️ for unrestricted AI conversations**
