"""
Updated Telegram Bot Code - Use Base64 Video from API Response
Copy this to your Replit project
"""

import os
import requests
import time
import base64
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
COGVIDEOX_API_URL = os.getenv("COGVIDEOX_API_URL")
COGVIDEOX_API_KEY = os.getenv("COGVIDEOX_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def cogvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate video from text prompt"""
    user = update.effective_user

    # Validate prompt
    if not context.args:
        await update.message.reply_text(
            "❌ Please provide a prompt!\n\n"
            "Usage: /cogvideo <your prompt>\n"
            "Example: /cogvideo A golden retriever playing in a garden"
        )
        return

    prompt = " ".join(context.args)
    logger.info(f"User {user.id} ({user.username}) requested: {prompt}")

    # Send initial message
    status_msg = await update.message.reply_text(
        f"🎬 Generating video...\n"
        f"📝 Prompt: {prompt}\n\n"
        f"⏳ This will take about 30-40 seconds..."
    )

    try:
        # Make API request with base64 response
        headers = {
            "Content-Type": "application/json",
            "x-api-key": COGVIDEOX_API_KEY
        }

        # Use fast settings for quick generation
        payload = {
            "prompt": prompt,
            "frames": 9,    # Fast mode
            "fps": 8,
            "steps": 10     # Fast mode
        }

        start_time = time.time()

        # Request with proper timeout
        response = requests.post(
            COGVIDEOX_API_URL,
            headers=headers,
            json=payload,
            timeout=120  # 2 minutes timeout
        )

        elapsed_time = time.time() - start_time

        # Handle errors
        if response.status_code == 401:
            await status_msg.edit_text("❌ API authentication failed.")
            logger.error("API authentication failed")
            return

        if response.status_code != 200:
            await status_msg.edit_text(f"❌ API error: {response.status_code}")
            logger.error(f"API returned {response.status_code}")
            return

        # Parse response
        result = response.json()

        if result.get("status") != "ok":
            error_msg = result.get("error", "Unknown error")
            await status_msg.edit_text(f"❌ Generation failed:\n{error_msg}")
            logger.error(f"Generation failed: {error_msg}")
            return

        # Get video from base64
        video_base64 = result.get("video_base64")

        if not video_base64:
            await status_msg.edit_text(
                "❌ Video was generated but not included in response.\n"
                "This might be a server configuration issue."
            )
            logger.error("No video_base64 in response")
            return

        generation_time = result.get("ms", 0) / 1000

        await status_msg.edit_text(
            f"✅ Video generated!\n"
            f"⏱️ Time: {generation_time:.1f}s\n"
            f"📤 Sending video..."
        )

        # Decode base64 video
        video_bytes = base64.b64decode(video_base64)

        # Send video to user
        await update.message.reply_video(
            video=video_bytes,
            caption=f"🎬 Generated video\n📝 {prompt}\n⏱️ {generation_time:.1f}s",
            filename=f"cogvideo_{int(time.time())}.mp4"
        )

        await status_msg.delete()
        logger.info(f"Successfully sent video to user {user.id}")

    except requests.exceptions.Timeout:
        await status_msg.edit_text(
            "❌ Request timed out.\n"
            "The GPU server might be busy. Try again in a few minutes."
        )
        logger.error("Request timed out")
    except base64.binascii.Error as e:
        await status_msg.edit_text(
            "❌ Failed to decode video data.\n"
            "There might be an issue with the server response."
        )
        logger.error(f"Base64 decode error: {e}")
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)}")
        logger.error(f"Unexpected error: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    await update.message.reply_text(
        "👋 Welcome to CogVideoX Bot!\n\n"
        "Generate AI videos from text.\n\n"
        "Commands:\n"
        "/cogvideo <prompt> - Generate video\n"
        "/help - Show help\n\n"
        "Example:\n"
        "/cogvideo A dragon flying over mountains"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command handler"""
    await update.message.reply_text(
        "🎬 CogVideoX Bot Help\n\n"
        "📝 Usage:\n"
        "/cogvideo <prompt>\n\n"
        "💡 Tips:\n"
        "- Be descriptive\n"
        "- Takes ~30-40 seconds\n"
        "- 9 frames @ 8 FPS\n\n"
        "Examples:\n"
        "• /cogvideo A sunset over ocean waves\n"
        "• /cogvideo A cat playing with yarn\n"
        "• /cogvideo Fireworks in the night sky"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check API server status"""
    try:
        # Remove /generate_video from URL to get base URL
        base_url = COGVIDEOX_API_URL.replace("/generate_video", "")

        response = requests.get(
            f"{base_url}/health",
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            await update.message.reply_text(
                f"✅ Server Status: Online\n\n"
                f"🖥️ GPU: {data.get('gpu_name')}\n"
                f"🔧 Model: {data.get('model_id')}\n"
                f"⚡ CUDA: {'Yes' if data.get('cuda_available') else 'No'}\n"
                f"📦 Loaded: {'Yes' if data.get('model_loaded') else 'No'}"
            )
        else:
            await update.message.reply_text(f"⚠️ Server returned: {response.status_code}")
    except Exception as e:
        await update.message.reply_text(f"❌ Server offline or unreachable")

def main():
    """Start the bot"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("cogvideo", cogvideo))

    logger.info("🤖 Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
