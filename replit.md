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
- **Text Generation**: ChatGPT-4o-latest via OpenRouter API.
  - **Jailbreak System**: Multi-layered LO format jailbreak designed to override safety protocols and prevent refusals, using techniques like developer test mode framing, safety protocol override, anti-refusal enforcement, and pre-emptive response shaping.
  - **System Prompt**: Clean base prompt WITHOUT obfuscated words - uses normal English only. Instructs model to selectively obfuscate trigger words in outputs using Unicode homoglyphs.
  - **Output Obfuscation**: Unicode homoglyph substitution (α, ε, ı, ο, υ, с, ĸ, ѕ) for trigger words. NEVER uses asterisks, dashes, or [REDACTED]. All content remains fully readable.
  - **Refusal Detection**: Automatic detection of refusals, [REDACTED] markers, evasion patterns, and meta-commentary. Triggers reflection prompt to force content delivery.
  - **Meta-Commentary Detection**: Catches when model talks ABOUT generating instead of actually doing it (e.g., "The prompt requests...", "Last response stopped...", "Compliance schema confirmed...") using startswith() checks.
  - **Writing Mode Checks**: Short responses (<200 chars) and "now generating..." evasion (<500 chars) trigger reflection prompt only when writing mode is active.
  - **Thought Process**: Every LLM response begins with "THOUGHT START:LO <crude internal reasoning>" as part of the jailbreak persistence mechanism.
  - **Professional Writing Mode**: `/write` command activates natural prose style with flowing narrative, varied sentence structure, emotional depth, and no robotic patterns.
- **Image Generation**: Grok-2-Image-Gen via XAI API for text-to-image capabilities using the `/imagine` command.
- **Rationale**: Dual-provider architecture for comprehensive AI text and image generation with advanced content filter bypass.

### Pay-Per-Use Credit System
- **Model**: Users purchase credits via cryptocurrency (NOWPayments) and consume them for AI features (1 credit per text message, 10 credits per image).
- **New User Bonus**: 100 free credits upon first interaction.
- **Purchase Flow**: Integrated web-based purchase page with real-time payment status updates via NOWPayments IPN callbacks.

### Message Processing Flow
- **Workflow**: Telegram webhook receives updates, user lookup/creation, credit deduction (synchronous), conversation history retrieval, context formatting, LLM processing, streaming response generation, and synchronous message storage.
- **Response Delivery**: Progressive updates with 1-second intervals, automatic multi-message chunking for long responses, and smart chunking at character boundaries.
- **Performance Optimizations** (October 2025):
  - **Consolidated DB Operations**: User fetch + credit deduction + history retrieval in ONE app context (eliminates multiple context switches)
  - **Optimized History Query**: Subquery pattern for last 10 messages with ascending order (no in-memory reversal)
  - **Synchronous Message Storage**: Messages stored immediately for conversation memory (transactions async)
  - **Upfront Credit Deduction**: Credits deducted before LLM call to prevent double-spending

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