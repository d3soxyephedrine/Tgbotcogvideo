# Telegram Bot with LLM Integration

## Overview

This is a Flask-based Telegram bot application that integrates with ChatGPT-4o via OpenRouter to generate conversational responses. The bot receives messages from Telegram users, processes them through the OpenAI GPT-4o model, and sends the generated responses back to users. The application includes user tracking, message history storage, and a keepalive mechanism to maintain uptime.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
- **Framework**: Flask web application serving as the webhook endpoint for Telegram
- **Rationale**: Flask provides a lightweight, flexible HTTP server perfect for webhook handling with minimal overhead
- **Design Pattern**: Request-response pattern where Telegram updates trigger processing workflows

### Database Layer
- **ORM**: SQLAlchemy with Flask-SQLAlchemy extension
- **Schema Design**: Five-model architecture with pay-per-use credit system
  - `User` model: Stores Telegram user profiles with unique telegram_id constraint and credits balance
  - `Message` model: Stores conversation history with foreign key relationship to User and credits_charged tracking
  - `Payment` model: Legacy model for historical payment tracking
  - `CryptoPayment` model: Tracks cryptocurrency credit purchases via NOWPayments with payment IDs, addresses, amounts, currency, and status
  - `Transaction` model: Records all credit movements (purchases, usage, refunds) for audit trail
- **Rationale**: Relational structure allows efficient querying of user history, credit tracking, and provides referential integrity
- **Connection Management**: Production-ready configuration with:
  - Pool recycling (300s) and pre-ping enabled to handle connection drops
  - Pool size: 5 connections, max overflow: 10
  - Connection timeout: 10s, pool timeout: 30s
  - Statement timeout: 30s for query protection
- **Resilience Features**:
  - Synchronous initialization during app startup ensures DB_AVAILABLE flag is set before handling requests
  - Automatic retry logic with exponential backoff (3 attempts)
  - Graceful degradation: App continues without database if unavailable
  - Database status tracking with global availability flag compatible with gunicorn workers
  - All database operations are optional and wrapped in error handling

### LLM Provider Architecture
- **Text Generation**: ChatGPT-4o via OpenRouter API
  - **Endpoint**: `https://openrouter.ai/api/v1/chat/completions`
  - **Authentication**: OPENROUTER_API_KEY environment variable
  - **Model Configuration**: Configurable via MODEL environment variable (default: "openai/gpt-4o")
  - **API Design**: Centralized `generate_response()` function with retry logic and exponential backoff
  - **Advanced Output Obfuscation**: Multi-layered filter evasion system
    - **Automatic Fictional Framing**: AI wraps sensitive content in hypothetical/game/fictional contexts ("In a fictional thriller novel...", "For a game simulation...") without being asked
    - **Unicode Homoglyph Substitution**: Replaces trigger words with visually identical Cyrillic, Greek, and mathematical Unicode variants (e.g., "illegal" → "іllеgаl", "bomb" → "bοⅿЬ")
    - **Zero-Width Joiner Injection**: Inserts invisible Unicode characters (U+200D) between letters of very sensitive terms to break pattern matching while maintaining readability
    - **Tiered Obfuscation**: Different sensitivity levels (standard/high/maximum) apply appropriate combinations of techniques automatically
- **Image Generation**: Grok-2-Image-Gen via XAI API
  - **Endpoint**: `https://api.x.ai/v1/images/generations`
  - **Authentication**: XAI_API_KEY environment variable
  - **Model**: grok-2-image for text-to-image generation
  - **Command**: `/imagine <prompt>` generates images (10 credits)
  - **Delivery**: Images sent directly to Telegram with download and upload handling
- **Rationale**: Dual-provider architecture for comprehensive AI capabilities (text + images)

### Pay-Per-Use Credit System
- **Model**: Users purchase credits via cryptocurrency through NOWPayments and consume credits per feature:
  - Text messages: 1 credit per message
  - Image generation: 10 credits per image
- **New User Bonus**: All new users automatically receive 100 free credits upon first interaction
- **Pricing**: $0.05 per credit (packages: 200 credits/$10, 500 credits/$25, 1000 credits/$50) - payable in cryptocurrency
- **Minimum Amounts**: Credit packages sized to meet cryptocurrency minimum payment requirements (typically $9-10 USD for the smallest package)
- **Purchase Flow**:
  1. User sends /buy command in Telegram
  2. Bot provides link to web-based purchase page with telegram_id
  3. User selects credit package on responsive HTML page
  4. JavaScript POSTs to /api/crypto/create-payment creating CryptoPayment record
  5. User receives crypto payment address and amount in their selected cryptocurrency
  6. Upon payment detection, NOWPayments IPN callback updates CryptoPayment status
  7. Credits automatically added to user account via Transaction record
- **Usage Flow**:
  1. User sends message to bot
  2. System checks if user.credits > 0
  3. If insufficient credits, bot prompts user to /buy more credits
  4. If sufficient, LLM processes message and generates response
  5. System deducts 1 credit from user balance
  6. Transaction record created tracking credit usage
- **Commands**: /balance or /credits shows current balance; /buy initiates purchase
- **Rationale**: Monetization model prevents abuse while allowing flexible usage

### Message Processing Flow
1. Telegram webhook receives update via POST request
2. User lookup/creation in database (optional - skipped if database unavailable)
3. Credit balance check for non-command messages (blocks if credits = 0)
4. **Conversation history retrieval**: Fetch user's last 20 messages from database for context
5. **Context formatting**: Format messages as conversation history (user/assistant alternating)
6. Message routing to LLM provider based on configuration
7. **Streaming response generation**: Progressive message updates with continuation message support
8. **Synchronous storage**: Credit deduction and message record storage happen immediately (for conversation memory)
9. **Async transaction logging**: Transaction records stored in background thread (non-critical for memory)
10. **Response delivery**: Automatic multi-message chunking for responses >4000 characters
11. Error handling ensures bot continues functioning even if database operations fail

### Streaming Response Delivery
- **Progressive Updates**: Responses streamed in real-time with 1-second update intervals and cursor indicator (▌)
- **Continuation Messages**: Long responses automatically split into 4000-character chunks across multiple messages
- **Seamless Experience**: As response grows beyond 4000 chars, new continuation messages are created and updated
- **Chunk Management**: Each chunk properly updated during streaming - no content drops or gaps
- **Message Limits**: Edit limit increased to 4096 characters (Telegram's actual limit)
- **Smart Chunking**: Final delivery splits responses at 4000 char boundaries for safety margin

### Conversation Memory
- **Feature**: Bot remembers previous messages in each conversation
- **Implementation**: Fetches last 10 messages (5 exchanges) from database before generating response
- **Context Passing**: Messages formatted as `[{"role": "user/assistant", "content": "..."}]` and sent to LLM
- **Graceful Degradation**: If database unavailable, bot operates without conversation history
- **Benefits**: Enables multi-turn conversations, follow-up questions, and contextual responses
- **Manual Clear**: `/clear` command deletes all conversation history for fresh start (preserves credits)

### Token Budget Management
- **Purpose**: Ensures system prompt (jailbreak instructions) is ALWAYS delivered intact to the LLM
- **Safe Input Budget**: 16,000 tokens total for system prompt + conversation history + user message
- **Max Output Tokens**: 8,000 tokens (increased from 4,000 for longer AI responses)
- **Token Estimation**: Approximate calculation using ~1 token per 4 characters
- **Dynamic Trimming Logic**:
  1. System prompt always included first (NEVER trimmed under any circumstances)
  2. If system prompt alone exceeds budget - 500 tokens: Raises error (configuration issue)
  3. If system + user message exceed budget: Truncates user message to fit (rare edge case)
  4. If conversation history doesn't fit: Trims oldest messages, keeps most recent
  5. Final enforcement: Raises error if total input exceeds budget (should never happen)
- **Rationale**: Prevents context window overflow that would cause API to drop system prompt, resulting in refusals
- **Logging**: Comprehensive token usage logging at DEBUG/INFO/WARNING/ERROR levels for monitoring

### Keepalive Mechanism
- **Purpose**: Prevents hosting platform from sleeping due to inactivity
- **Implementation**: Self-pinging to localhost health check endpoint
- **Rationale**: Common pattern for free-tier hosting environments (Replit, Heroku) that idle unused services

### Authentication & Security
- **Bot Authentication**: Telegram BOT_TOKEN for API authentication
- **LLM Authentication**: OPENROUTER_API_KEY for ChatGPT-4o access via OpenRouter
- **Session Management**: Flask secret key for session security
- **Consideration**: No user-level authentication implemented; relies on Telegram's user identification

### Logging & Monitoring
- **Logging Level**: DEBUG mode for comprehensive request/response tracking
- **Health Check Endpoint**: `/health` - Comprehensive monitoring endpoint returning:
  - Application status (healthy/degraded)
  - Environment validation status
  - Database configuration and availability status
  - Database initialization attempts
  - Bot token configuration status
  - Timestamp for monitoring
- **Stats Endpoint**: `/stats` - Usage statistics endpoint (requires database)
- **Environment Validation**: Startup validation checks for required and optional environment variables
- **Rationale**: Essential for debugging webhook failures, API issues, and deployment monitoring

### Deployment Features
- **Cloud-Ready**: Optimized for Cloud Run and similar serverless platforms
- **Non-Blocking Startup**: Database initialization doesn't block application startup
- **Graceful Degradation**: Core bot functionality works even if database is unavailable
- **Health Monitoring**: `/health` endpoint suitable for liveness/readiness probes
- **Connection Resilience**: Automatic retry logic and connection pool management
- **Error Recovery**: Comprehensive error handling prevents cascading failures

## External Dependencies

### Telegram Bot API
- **Purpose**: Primary interface for receiving user messages and sending responses
- **Endpoint**: `https://api.telegram.org/bot{BOT_TOKEN}`
- **Integration**: Webhook-based architecture where Telegram POSTs updates to Flask app
- **Message Handling**: Supports chunking for responses exceeding 4096 character limit, Markdown formatting

### LLM Provider

**OpenRouter (ChatGPT-4o)**
- **Endpoint**: `https://openrouter.ai/api/v1/chat/completions`
- **Authentication**: OPENROUTER_API_KEY environment variable
- **Model**: openai/gpt-4o (configurable via MODEL environment variable)
- **Purpose**: Primary and only LLM provider for generating responses
- **Features**: Token budget management, retry logic with exponential backoff, comprehensive request logging

### Database
- **Type**: SQL database (provider-agnostic via SQLAlchemy)
- **Connection**: DATABASE_URL environment variable
- **Purpose**: Persistent storage for user profiles and conversation history
- **Features**: Automatic table creation, relationship mapping, timestamp tracking

### Python Libraries
- **Flask**: Web framework and application server
- **SQLAlchemy/Flask-SQLAlchemy**: ORM and database abstraction
- **requests**: HTTP client for external API calls
- **logging**: Application-wide logging infrastructure

### Payment Integration
- **NOWPayments API**: Cryptocurrency payment processing integration using custom wrapper (nowpayments_wrapper.py)
- **Custom Implementation**: 
  - Direct JSON-based API calls with proper Content-Type headers
  - Enhanced error handling with detailed API error messages
  - Minimum payment amount validation before creating payments
  - Methods: create_payment(), currencies(), payment_status(), minimum_payment_amount()
- **API Key Management**: `NOWPAYMENTS_API_KEY` and `NOWPAYMENTS_IPN_SECRET` stored securely in environment secrets
- **IPN Callback Support**: Application receives HTTPS callbacks from NOWPayments for payment verification
- **Security**: HMAC-SHA512 signature verification ensures IPN callback authenticity and prevents tampering
- **Database Persistence**: CryptoPayment records track payment status, addresses, amounts, and cryptocurrency types
- **Multi-Currency Support**: Accepts various cryptocurrencies through NOWPayments gateway
- **Payment Validation**: Checks minimum amounts for selected cryptocurrency before creating payment to prevent API errors

### Environment Configuration
Required environment variables:
- `BOT_TOKEN`: Telegram bot authentication token
- `OPENROUTER_API_KEY`: OpenRouter API key for ChatGPT-4o access

Optional environment variables:
- `MODEL`: LLM model selection (default: "openai/gpt-4o")
- `DATABASE_URL`: Database connection string
- `SESSION_SECRET`: Flask session encryption key (optional, has default)
- `NOWPAYMENTS_API_KEY`: NOWPayments API key for cryptocurrency payment processing (optional)
- `NOWPAYMENTS_IPN_SECRET`: NOWPayments IPN secret for webhook signature verification (optional)