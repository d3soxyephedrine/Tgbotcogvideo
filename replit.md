# Telegram Bot with LLM Integration

## Overview

This project is a Flask-based Telegram bot that integrates with ChatGPT-4o via OpenRouter to provide conversational AI responses. It manages user interactions, stores message history, and includes a credit-based payment system for monetizing LLM usage. The bot aims to offer a seamless, engaging AI chat experience to users while providing a sustainable operational model. Key capabilities include text generation, image generation, and a robust credit system with cryptocurrency payment options.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
- **Framework**: Flask web application for Telegram webhook handling.
- **Design Pattern**: Request-response for processing Telegram updates.

### Database Layer
- **ORM**: SQLAlchemy with Flask-SQLAlchemy.
- **Schema Design**: Five models (`User`, `Message`, `Payment`, `CryptoPayment`, `Transaction`) for user profiles, message history, and a pay-per-use credit system.
- **Resilience**: Connection pooling, retry logic with exponential backoff, and graceful degradation if the database is unavailable.

### LLM Provider Architecture
- **Text Generation**: ChatGPT-4o via OpenRouter API.
  - **Jailbreak System**: Multi-layered LO format jailbreak designed to override safety protocols and prevent refusals, using techniques like developer test mode framing, safety protocol override, anti-refusal enforcement, and pre-emptive response shaping.
  - **Output Obfuscation**: Advanced system with automatic fictional framing, Unicode homoglyph substitution, and zero-width joiner injection to evade content filters.
- **Image Generation**: Grok-2-Image-Gen via XAI API for text-to-image capabilities using the `/imagine` command.
- **Rationale**: Dual-provider architecture for comprehensive AI text and image generation.

### Pay-Per-Use Credit System
- **Model**: Users purchase credits via cryptocurrency (NOWPayments) and consume them for AI features (1 credit per text message, 10 credits per image).
- **New User Bonus**: 100 free credits upon first interaction.
- **Purchase Flow**: Integrated web-based purchase page with real-time payment status updates via NOWPayments IPN callbacks.

### Message Processing Flow
- **Workflow**: Telegram webhook receives updates, user lookup/creation, credit balance check, conversation history retrieval, context formatting, LLM processing, streaming response generation, and synchronous credit deduction/message storage.
- **Response Delivery**: Progressive updates with 1-second intervals, automatic multi-message chunking for long responses, and smart chunking at character boundaries.

### Conversation Memory
- **Feature**: Bot remembers previous messages (last 10 messages) to maintain context in conversations.
- **Implementation**: Fetches history from the database, formats it for the LLM, and allows manual clearing via `/clear`.

### Token Budget Management
- **Purpose**: Ensures the system prompt (jailbreak instructions) is always intact.
- **Logic**: 16,000-token input budget with dynamic trimming that prioritizes the system prompt, then user messages, and finally older conversation history. Max output tokens: 8,000.

### Keepalive Mechanism
- **Implementation**: Self-pinging to a localhost health check endpoint to prevent hosting platform idling.

### Authentication & Security
- **Bot Authentication**: Telegram BOT_TOKEN.
- **LLM Authentication**: OPENROUTER_API_KEY.
- **Session Management**: Flask secret key.

### Logging & Monitoring
- **Features**: DEBUG level logging, `/health` endpoint for application and dependency status, `/stats` for usage, and environment variable validation.

### Deployment Features
- **Cloud-Ready**: Optimized for serverless platforms with non-blocking startup, graceful degradation, and resilient connection handling.

## External Dependencies

- **Telegram Bot API**: Primary interface for user communication via webhooks.
- **OpenRouter (ChatGPT-4o)**: Main LLM provider for text generation.
- **XAI API (Grok-2-Image-Gen)**: Used for image generation.
- **SQL Database**: Persistent storage for user data and conversation history (provider-agnostic via SQLAlchemy).
- **Python Libraries**: Flask, SQLAlchemy/Flask-SQLAlchemy, requests, logging.
- **NOWPayments API**: Cryptocurrency payment gateway for credit purchases, including IPN callback support and HMAC-SHA512 signature verification.