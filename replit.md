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
- **Schema Design**: Five models (`User`, `Message`, `Payment`, `CryptoPayment`, `Transaction`) for user profiles, message history, and a pay-per-use credit system. Extensions include columns for daily credits, purchase tracking, action history, and `api_key` for web access. The `Message` model includes a `platform` column to track message source (Telegram or web).
- **Resilience**: Connection pooling, retry logic, and graceful degradation.

### LLM Provider Architecture
- **Text Generation**: ChatGPT-4o-latest via OpenRouter API.
  - **Jailbreak System**: Multi-layered LO format jailbreak designed to override safety protocols and prevent refusals, using techniques like developer test mode framing and anti-refusal enforcement. Includes an anti-leak protocol and system prompt with Unicode homoglyph output obfuscation for trigger words.
  - **Refusal/Meta-Commentary Detection**: Automatic detection and reflection prompts to ensure content delivery and prevent evasive responses.
  - **Thought Process**: Every LLM response begins with "THOUGHT START:LO <crude internal reasoning>".
  - **Professional Writing Mode**: `/write` command activates natural prose style.
- **Image Generation (Quadruple Models)**:
  - **FLUX.1 Kontext Max** (`/imagine`): High-quality photorealistic images via Novita AI. (5 credits/image)
  - **Hunyuan-Image-3** (`/uncensored`): Fully uncensored images via Novita AI. (5 credits/image)
  - **Grok-2-Image** (`/grok`): Stylized images via xAI API. (4 credits/image)
  - **Qwen-Image** (`/edit`): Image editing capabilities via Novita AI. (3 credits/image)
- **Image Editing (Dual Models)**:
  - **FLUX.1 Kontext Max**: Image editing with maximum permissiveness via Novita AI. (6 credits/edit)
  - **Qwen-Image**: Image editing via Novita AI. (5 credits/edit)
- **Video Generation (Single Model - Image-to-Video)**:
  - **WAN 2.5 I2V Preview** (`/img2video`): Converts images to videos via Novita AI, with async task processing. (10 credits/video)

### Pay-Per-Use Credit System with Daily Freebies
- **Credit Types**: Daily free credits (25 credits, 48h expiry, 24h cooldown) and purchased credits with volume bonuses.
- **Deduction Logic**: Daily credits used first, then purchased credits.
- **Pricing**: Text messages (1 credit), image generation (3-5 credits), image editing (5-6 credits), video generation (10 credits).
- **Monetization Features**: Video generation locked until first purchase. New users receive 100 free credits.
- **Purchase Flow**: Integrated web-based purchase page with NOWPayments for cryptocurrency payments and IPN callbacks.

### Message Processing Flow
- **Workflow**: Telegram updates trigger user handling, synchronous credit deduction, conversation history retrieval, context formatting, LLM processing, streaming response generation, and synchronous message storage.
- **Response Delivery**: Progressive updates, multi-message chunking, and smart chunking at character boundaries.
- **Performance Optimizations**: Consolidated database operations, optimized history queries, upfront credit deduction, and background processing for image/video generation to prevent webhook timeouts.

### Conversation Memory
- The bot remembers the last 10 messages for context, with manual clearing via `/clear`.

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
- **Architecture**: `/v1/chat/completions` endpoint provides an OpenAI-compatible API. Shared credit pool and unified database for web and Telegram users.
- **Authentication**: API keys obtained via `/getapikey` Telegram command.
- **Credit System**: Web requests cost 1 credit/message, same deduction logic as Telegram. Credits are refunded on OpenRouter failure.
- **Error Responses**: 401 (Invalid API key), 402 (Insufficient credits), 500 (Server error), 502 (OpenRouter API error).

### Web Chat Interface
- **Overview**: Built-in ChatGPT-style web interface at `/chat` for text-only conversations.
- **Features**: Modern UI, streaming responses, real-time credit balance display, API key authentication (saved in localStorage), shared credit system, and identical uncensored system prompt as Telegram.
- **Technical Details**: Uses existing `/v1/chat/completions` proxy and `/api/balance` endpoint. Messages stored with `platform='web'`.
- **Differences from Telegram**: Text-only, session-based history, no commands.

## External Dependencies

- **Telegram Bot API**: User communication.
- **OpenRouter**: Main LLM provider (ChatGPT-4o).
- **Novita AI**: Image generation (FLUX.1 Kontext Max, Hunyuan-Image-3, Qwen-Image) and image-to-video (WAN 2.5 I2V Preview).
- **xAI API**: Grok-2-Image for image generation.
- **SQL Database**: Persistent data storage.
- **Python Libraries**: Flask, SQLAlchemy/Flask-SQLAlchemy, requests, logging.
- **NOWPayments API**: Cryptocurrency payment gateway.
- **LibreChat**: Optional open-source web UI integration.