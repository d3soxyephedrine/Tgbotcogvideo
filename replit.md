# Telegram Bot with LLM Integration

## Overview

This is a Flask-based Telegram bot application that integrates with Large Language Model (LLM) APIs to generate conversational responses. The bot receives messages from Telegram users, processes them through either DeepSeek or Grok LLM providers, and sends the generated responses back to users. The application includes user tracking, message history storage, and a keepalive mechanism to maintain uptime.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
- **Framework**: Flask web application serving as the webhook endpoint for Telegram
- **Rationale**: Flask provides a lightweight, flexible HTTP server perfect for webhook handling with minimal overhead
- **Design Pattern**: Request-response pattern where Telegram updates trigger processing workflows

### Database Layer
- **ORM**: SQLAlchemy with Flask-SQLAlchemy extension
- **Schema Design**: Two-model architecture
  - `User` model: Stores Telegram user profiles with unique telegram_id constraint
  - `Message` model: Stores conversation history with foreign key relationship to User
- **Rationale**: Relational structure allows efficient querying of user history and provides referential integrity
- **Connection Management**: Pool recycling (300s) and pre-ping enabled to handle connection drops in cloud environments

### LLM Provider Architecture
- **Multi-Provider Support**: Enum-based provider selection system
  - DeepSeek via Together.ai API
  - Grok via xAI API
- **Runtime Selection**: Provider determined by MODEL environment variable prefix
- **Rationale**: Abstraction layer allows switching between providers without code changes, enabling A/B testing and failover scenarios
- **API Design**: Centralized `generate_response()` function routes to appropriate provider based on configuration

### Message Processing Flow
1. Telegram webhook receives update via POST request
2. User lookup/creation in database with last_interaction timestamp update
3. Message routing to LLM provider based on configuration
4. Response generation with system prompt injection
5. Message and response persistence to database
6. Response delivery to Telegram with chunking for messages >4000 characters

### Keepalive Mechanism
- **Purpose**: Prevents hosting platform from sleeping due to inactivity
- **Implementation**: Self-pinging to localhost health check endpoint
- **Rationale**: Common pattern for free-tier hosting environments (Replit, Heroku) that idle unused services

### Authentication & Security
- **Bot Authentication**: Telegram BOT_TOKEN for API authentication
- **LLM Authentication**: Separate API keys (API_KEY for DeepSeek, XAI_API_KEY for Grok)
- **Session Management**: Flask secret key for session security
- **Consideration**: No user-level authentication implemented; relies on Telegram's user identification

### Logging & Monitoring
- **Logging Level**: DEBUG mode for comprehensive request/response tracking
- **Stats Endpoint**: Dedicated route for monitoring (implementation in progress)
- **Rationale**: Essential for debugging webhook failures and API issues in production

## External Dependencies

### Telegram Bot API
- **Purpose**: Primary interface for receiving user messages and sending responses
- **Endpoint**: `https://api.telegram.org/bot{BOT_TOKEN}`
- **Integration**: Webhook-based architecture where Telegram POSTs updates to Flask app
- **Message Handling**: Supports chunking for responses exceeding 4096 character limit, Markdown formatting

### LLM Providers

**Together.ai (DeepSeek)**
- **Endpoint**: `https://api.together.xyz/inference`
- **Authentication**: API_KEY environment variable
- **Purpose**: Primary LLM provider for DeepSeek models
- **Configuration**: Model selection via MODEL environment variable

**xAI (Grok)**
- **Endpoint**: Not fully visible in provided code
- **Authentication**: XAI_API_KEY environment variable
- **Purpose**: Alternative LLM provider for Grok models (grok-2-1212 default)
- **Selection**: Activated when MODEL starts with "grok"

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

### Environment Configuration
Required environment variables:
- `BOT_TOKEN`: Telegram bot authentication token
- `API_KEY`: Together.ai API key for DeepSeek
- `XAI_API_KEY`: xAI API key for Grok
- `MODEL`: LLM model selection (default: "grok-2-1212")
- `DATABASE_URL`: Database connection string
- `SESSION_SECRET`: Flask session encryption key (optional, has default)