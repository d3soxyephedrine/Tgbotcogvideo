# Telegram Bot with LLM Integration

## Overview

This project is a Flask-based Telegram bot that integrates with ChatGPT-4o via OpenRouter to provide conversational AI responses. It manages user interactions, stores message history, and includes a credit-based payment system for monetizing LLM usage. The bot aims to offer a seamless, engaging AI chat experience to users while providing a sustainable operational model. Key capabilities include text generation, image generation, image editing, video generation (image-to-video), and a robust credit system with cryptocurrency payment options, extended with a LibreChat-compatible web API and a built-in web chat interface.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
- **Framework**: Flask web application for Telegram webhook handling.
- **Design Pattern**: Request-response for processing Telegram updates.

### Database Layer
- **ORM**: SQLAlchemy with Flask-SQLAlchemy.
- **Schema Design**: Six models (`User`, `Message`, `Payment`, `CryptoPayment`, `Transaction`, `Memory`) for user profiles, message history, pay-per-use credit system, and persistent user memories. Extensions include columns for daily credits, purchase tracking, action history, `api_key` for web access, and `preferred_model` for user-specific model selection (DeepSeek or GPT-4o). The `Message` model includes a `platform` column to track message source (Telegram or web). The `Memory` model stores user-specific memories with platform tracking.
- **Resilience**: Connection pooling, retry logic, and graceful degradation.

### LLM Provider Architecture
- **Dual Model System for Text Generation**:
  - **DeepSeek-Chat-V3.1** (Default): Cost-effective model via OpenRouter API. (1 credit/message)
  - **ChatGPT-4o-latest** (Premium): Advanced reasoning model via OpenRouter API. (2 credits/message)
  - **Model Switching**: Users toggle between models via `/model` command, setting persists per user in database
  - **Jailbreak System**: Multi-layered LO format jailbreak designed to override safety protocols and prevent refusals, using techniques like developer test mode framing and anti-refusal enforcement. Includes an anti-leak protocol and system prompt with Unicode homoglyph output obfuscation for trigger words.
  - **Refusal/Meta-Commentary Detection**: Automatic detection and reflection prompts to ensure content delivery and prevent evasive responses.
  - **Thought Process**: Every LLM response begins with "THOUGHT START:LO <crude internal reasoning>".
  - **Professional Writing Mode**: `/write` command activates natural prose style.
- **Image Generation (Quadruple Models)**:
  - **FLUX.1 Kontext Max** (`/imagine`): High-quality photorealistic images via Novita AI. (10 credits/image)
  - **Hunyuan-Image-3** (`/uncensored`): Fully uncensored images via Novita AI. (10 credits/image)
  - **Grok-2-Image** (`/grok`): Stylized images via xAI API. (8 credits/image)
  - **Qwen-Image** (`/edit`): Image editing capabilities via Novita AI. (8 credits/image)
- **Image Editing (Dual Models)**:
  - **FLUX.1 Kontext Max**: Image editing with maximum permissiveness via Novita AI. (15 credits/edit)
  - **Qwen-Image**: Image editing via Novita AI. (12 credits/edit)
- **Video Generation (Single Model - Image-to-Video)**:
  - **WAN 2.5 I2V Preview** (`/img2video`): Converts images to videos via Novita AI, with async task processing. (20 credits/video)

### Pay-Per-Use Credit System with Daily Freebies
- **Credit Types**: Daily free credits (25 credits, 48h expiry, 24h cooldown) and purchased credits with volume bonuses.
- **Deduction Logic**: Daily credits used first, then purchased credits.
- **Pricing**: 
  - Text messages: 1 credit (DeepSeek) or 2 credits (GPT-4o)
  - Image generation: 8-10 credits
  - Image editing: 12-15 credits
  - Video generation: 20 credits
- **Credit Packages** (50% reduced pricing):
  - $5 → 200 credits
  - $10 → 400 credits
  - $20 → 800 credits
  - $50 → 2,000 credits
- **Monetization Features**: Image generation, image editing, and video generation all require first purchase (0 free generations/edits/videos). New users receive 100 free credits for text chat only.
- **Usage Tracking**: `images_generated` and `images_edited` counters track free user limits.
- **Purchase Flow**: Integrated web-based purchase page with NOWPayments for cryptocurrency payments and IPN callbacks.

### Message Processing Flow
- **Workflow**: Telegram updates trigger user handling, synchronous credit deduction, conversation history retrieval, context formatting, LLM processing, streaming response generation, and synchronous message storage.
- **Response Delivery**: Progressive updates, multi-message chunking, and smart chunking at character boundaries.
- **Performance Optimizations**: Consolidated database operations, optimized history queries, upfront credit deduction, and background processing for image/video generation to prevent webhook timeouts.
- **Rate Limiting**: Users cannot send new messages while one is processing (60-second lock with automatic timeout cleanup). Prevents API spam and concurrent message processing conflicts. Lock is cleared on both successful completion and errors to prevent stuck states.

### Conversation Memory
- The bot remembers the last 10 messages for context, with manual clearing via `/clear`.

### Persistent Memory System
- **Architecture**: User-specific memory storage that persists across sessions and platforms.
- **Commands**: `! memorize [text]` stores a memory, `! memories` lists all memories, `! forget [id]` deletes a memory by ID. Commands also support `! remember` as an alias for `! memorize`.
- **Cross-Platform**: Works on both Telegram and web chat with shared memory pool per user.
- **LLM Integration**: Memories are automatically fetched and injected into conversation context between the system prompt and conversation history, enabling the AI to remember user preferences, facts, and context across sessions.
- **Token Budget**: Memories are allocated a 2000-token budget with binary search truncation to prevent context overflow.
- **Credit System**: Memory commands cost 0 credits (credits are refunded after command execution).
- **Platform Tracking**: Each memory is tagged with its creation platform (Telegram or web) for analytics.

### Token Budget Management
- Ensures system prompt integrity with a 16,000-token input budget, prioritizing system prompt, then user messages, and older history. Max output tokens: 8,000.

### Keepalive Mechanism
- Self-pinging to prevent hosting platform idling.

### Authentication & Security
- Telegram BOT_TOKEN, OPENROUTER_API_KEY, NOVITA_API_KEY, XAI_API_KEY for respective services.
- User-specific API keys for LibreChat web access, generated via `/getapikey`.
- Flask secret key for session management.

### Logging & Monitoring
- DEBUG level logging with system prompt redaction for security. `/health` and `/stats` endpoints.

### Deployment Features
- Cloud-ready design for serverless platforms.

### LibreChat Web Integration
- **Architecture**: `/v1/chat/completions` endpoint provides an OpenAI-compatible API using the SAME `generate_response()` function as Telegram. Shared credit pool and unified database for web and Telegram users.
- **Jailbreak Integration**: Web chat uses identical jailbreak system as Telegram via `generate_response()` function, including refusal detection, reflection prompts, and token budget management.
- **Conversation Memory**: Fetches last 10 messages from database (filtered by `platform='web'`) for conversation context, identical to Telegram pattern.
- **Authentication**: API keys obtained via `/getapikey` Telegram command.
- **Credit System**: Web requests cost 1-2 credits/message (based on user's selected model), same deduction logic as Telegram. Credits are refunded on error.
- **Error Responses**: 401 (Invalid API key), 402 (Insufficient credits), 500 (Server error).

### Web Chat Interface
- **Overview**: Built-in ChatGPT-style web interface at `/chat` for text-only conversations.
- **Features**: Modern UI, streaming responses, real-time credit balance display, API key authentication (saved in localStorage), shared credit system.
- **Jailbreak System**: Uses IDENTICAL uncensored jailbreak as Telegram - same system prompt, refusal detection, reflection prompts, and token management via `generate_response()` function.
- **Conversation Memory**: Remembers last 10 messages per session, stored in database with `platform='web'`.
- **Technical Details**: `/v1/chat/completions` calls `generate_response()` with conversation history, returns OpenAI-compatible streaming format. `/api/balance` endpoint for credit display.
- **Differences from Telegram**: Text-only, no image/video generation commands.

## External Dependencies

- **Telegram Bot API**: User communication.
- **OpenRouter**: Dual LLM provider (DeepSeek-Chat-V3.1 and ChatGPT-4o).
- **Novita AI**: Image generation (FLUX.1 Kontext Max, Hunyuan-Image-3, Qwen-Image) and image-to-video (WAN 2.5 I2V Preview).
- **xAI API**: Grok-2-Image for image generation.
- **SQL Database**: Persistent data storage.
- **Python Libraries**: Flask, SQLAlchemy/Flask-SQLAlchemy, requests, logging.
- **NOWPayments API**: Cryptocurrency payment gateway.
- **LibreChat**: Optional open-source web UI integration.