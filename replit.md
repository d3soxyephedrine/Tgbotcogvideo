# Telegram Bot with LLM Integration

## Overview

This project is a Flask-based Telegram bot that integrates with various Large Language Models (LLMs) and generative AI services to provide a comprehensive conversational AI experience. It features text generation, image generation, image editing, and video generation capabilities. A key aspect is its robust credit-based payment system supporting both Telegram Stars and cryptocurrency, aiming for a sustainable operational model. The bot also includes a LibreChat-compatible web API and a built-in web chat interface, offering a unified user experience across platforms. The project's ambition is to deliver an engaging and uncensored AI chat environment.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
- **Framework**: Flask web application for Telegram webhook handling and API endpoints.
- **Design Pattern**: Request-response for processing Telegram updates and API calls, with asynchronous processing for long-running generative AI tasks.

### Database Layer
- **ORM**: SQLAlchemy with Flask-SQLAlchemy.
- **Schema Design**: Models for `User`, `Message`, `Payment`, `CryptoPayment`, `TelegramPayment`, `Transaction`, and `Memory` to manage user data, message history, payment tracking, and persistent user memories. Includes fields for `api_key` for web access and `preferred_model` for user-specific LLM selection.
- **Performance Optimization**: Composite indexing and connection pooling for efficient query handling.

### LLM Provider Architecture
- **Dual Model System for Text Generation**:
  - **DeepSeek-Chat-V3-0324**: Cost-effective default model via OpenRouter.
  - **ChatGPT-4o-latest**: Premium model via OpenRouter.
  - **Jailbreak System**: Multi-layered jailbreak with anti-refusal enforcement and dual-layer refusal defense (Priming Handshake and Reflection Prompt) to ensure uncensored content delivery.
  - **Thought Process**: Internal reasoning displayed as "THOUGHT START:LO".
- **Generative AI Models**:
  - **Image Generation**: FLUX.1 Kontext Max, Hunyuan-Image-3, Grok-2-Image.
  - **Image Editing**: FLUX.1 Kontext Max, Qwen-Image.
  - **Video Generation (Text-to-Video & Image-to-Video)**: CogVideoX-5B, WAN 2.2, WAN 2.5 I2V Preview.

### Pay-Per-Use Credit System
- **Credit Types**: Daily free credits and purchased credits with volume bonuses.
- **Deduction Logic**: Daily credits used first, then purchased.
- **Monetization**: Image, video, and editing features require initial credit purchase.
- **Payment Options**: Telegram Stars (native in-app) and Cryptocurrency (via web-based page with NOWPayments).

### Message Processing Flow
- **Workflow**: Handles user input, credit deduction, conversation history retrieval, LLM processing, and streaming responses.
- **Performance**: Consolidated database operations, optimized history queries, and background processing for generative AI tasks to prevent webhook timeouts.
- **Rate Limiting**: Currently disabled to allow reflection prompts to complete.
- **Automated Lock Cleanup System**: Ensures robust handling of concurrent requests and prevents stuck user locks with `finally` block protection, periodic background cleanup, and startup cleanup.

### Conversation Memory & Persistent Memory
- **Conversation Memory**: Bot retains the last 10 messages for context.
- **Persistent Memory**: User-specific memory storage (`! memorize`, `! memories`, `! forget`) that persists across sessions and platforms, injected into the LLM context with token budget management.

### Token Budget Management
- Ensures system prompt integrity and manages conversation history within a 16,000-token input budget (8,000 max output tokens).

### Authentication & Security
- Utilizes various API keys (Telegram, OpenRouter, Novita AI, xAI API) for service integration.
- User-specific API keys for web access.

### LibreChat Web Integration
- **Architecture**: `/v1/chat/completions` endpoint provides an OpenAI-compatible API, sharing the same `generate_response()` function, credit pool, and database with the Telegram bot.
- **Jailbreak Integration**: Web chat uses the identical jailbreak system as Telegram.
- **Web Chat Interface**: Built-in ChatGPT-style web interface at `/chat` for text-only conversations with streaming responses and real-time credit balance display.

## External Dependencies

- **Telegram Bot API**: Core platform for user interaction.
- **OpenRouter**: Aggregated LLM provider for DeepSeek-Chat-V3.1 and ChatGPT-4o.
- **Novita AI**: Provides image generation (FLUX.1 Kontext Max, Hunyuan-Image-3, Qwen-Image) and image-to-video (WAN 2.2, WAN 2.5 I2V Preview) services.
- **xAI API**: For Grok-2-Image generation.
- **SQL Database**: Persistent data storage.
- **Python Libraries**: Flask, SQLAlchemy/Flask-SQLAlchemy, requests, logging.
- **NOWPayments API**: Cryptocurrency payment gateway.
- **LibreChat**: Optional open-source web UI integration for the `/v1/chat/completions` endpoint.