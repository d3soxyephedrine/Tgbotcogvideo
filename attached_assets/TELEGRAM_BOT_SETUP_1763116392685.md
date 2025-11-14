# Telegram Bot Setup Guide for Replit

This guide shows you how to connect your Telegram bot (running on Replit) to your CogVideoX API server.

---

## Overview

Your setup consists of:
- **GPU Server** (Novita): Running CogVideoX-5B API at `http://proxy.us-ca-6.gpu-instance.novita.ai:8080`
- **Replit**: Running your Telegram bot that calls the CogVideoX API

---

## Step 1: Configure Replit Secrets

1. Open your Replit project
2. Click the **"Secrets"** icon (lock icon) in the left sidebar
3. Add the following secrets:

### Required Secrets

**Secret 1: COGVIDEOX_API_URL**
- **Key**: `COGVIDEOX_API_URL`
- **Value**: `http://proxy.us-ca-6.gpu-instance.novita.ai:8080/generate_video`

**Secret 2: COGVIDEOX_API_KEY**
- **Key**: `COGVIDEOX_API_KEY`
- **Value**: `3b8cae05212822b0c5f2166719d6d7a1cc568f53af023292cdb19aedaafccf43`

**Secret 3: TELEGRAM_BOT_TOKEN** (if not already set)
- **Key**: `TELEGRAM_BOT_TOKEN`
- **Value**: Your Telegram bot token from @BotFather

---

## Step 2: Update Your Telegram Bot Code

### Option A: Python Bot (python-telegram-bot library)

Create or update your bot handler:

```python
import os
import requests
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Get configuration from environment
COGVIDEOX_API_URL = os.getenv("COGVIDEOX_API_URL")
COGVIDEOX_API_KEY = os.getenv("COGVIDEOX_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def cogvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Generate video from text prompt
    Usage: /cogvideo A dragon flying over mountains
    """
    # Check if prompt was provided
    if not context.args:
        await update.message.reply_text(
            "❌ Please provide a prompt!\n\n"
            "Usage: /cogvideo <your prompt>\n"
            "Example: /cogvideo A golden retriever playing in a garden"
        )
        return

    # Get the prompt from command arguments
    prompt = " ".join(context.args)

    # Send initial message
    status_msg = await update.message.reply_text(
        f"🎬 Generating video...\n"
        f"📝 Prompt: {prompt}\n\n"
        f"⏳ This will take about 60 seconds..."
    )

    try:
        # Prepare API request
        headers = {
            "Content-Type": "application/json",
            "x-api-key": COGVIDEOX_API_KEY
        }

        payload = {
            "prompt": prompt,
            "frames": 13,
            "fps": 8,
            "steps": 15
        }

        # Make API request with timeout
        start_time = time.time()
        response = requests.post(
            COGVIDEOX_API_URL,
            headers=headers,
            json=payload,
            timeout=180  # 3 minutes timeout
        )

        elapsed_time = int(time.time() - start_time)

        # Check response
        if response.status_code == 401:
            await status_msg.edit_text("❌ API authentication failed. Please check API key configuration.")
            return

        if response.status_code != 200:
            await status_msg.edit_text(f"❌ API request failed with status {response.status_code}")
            return

        # Parse response
        result = response.json()

        if result.get("status") != "ok":
            error_msg = result.get("error", "Unknown error")
            await status_msg.edit_text(f"❌ Video generation failed:\n{error_msg}")
            return

        # Success! Get video URL
        video_url = result.get("video_url")
        video_path = result.get("video_path")
        generation_time = result.get("ms", 0) / 1000

        # Update status message
        await status_msg.edit_text(
            f"✅ Video generated successfully!\n"
            f"⏱️ Generation time: {generation_time:.1f}s\n"
            f"📥 Downloading video..."
        )

        # Download the video
        video_response = requests.get(video_url, timeout=60)

        if video_response.status_code == 200:
            # Send video to user
            await update.message.reply_video(
                video=video_response.content,
                caption=f"🎬 Generated video\n📝 Prompt: {prompt}\n⏱️ Generated in {generation_time:.1f}s",
                filename=f"cogvideo_{int(time.time())}.mp4"
            )

            # Delete status message
            await status_msg.delete()
        else:
            await status_msg.edit_text(
                f"✅ Video generated but download failed.\n"
                f"You can access it here: {video_url}"
            )

    except requests.exceptions.Timeout:
        await status_msg.edit_text(
            "❌ Request timed out. The GPU server might be overloaded.\n"
            "Please try again in a few minutes."
        )
    except requests.exceptions.RequestException as e:
        await status_msg.edit_text(f"❌ Network error: {str(e)}")
    except Exception as e:
        await status_msg.edit_text(f"❌ Unexpected error: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        "👋 Welcome to CogVideoX Bot!\n\n"
        "Generate videos from text with AI.\n\n"
        "Commands:\n"
        "/cogvideo <prompt> - Generate a video\n"
        "/help - Show this help message\n\n"
        "Example:\n"
        "/cogvideo A dragon flying over a neon city at night"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        "🎬 CogVideoX Bot Help\n\n"
        "📝 How to use:\n"
        "/cogvideo <your prompt> - Generate a video from text\n\n"
        "💡 Tips:\n"
        "- Be descriptive with your prompts\n"
        "- Videos take ~60 seconds to generate\n"
        "- Each video is 13 frames at 8 FPS\n\n"
        "📋 Examples:\n"
        "• /cogvideo A golden retriever playing in a sunny garden\n"
        "• /cogvideo A spaceship landing on Mars with dust clouds\n"
        "• /cogvideo Ocean waves crashing on a beach at sunset"
    )

def main():
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cogvideo", cogvideo))

    # Run the bot
    print("🤖 Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
```

### Option B: Node.js Bot (node-telegram-bot-api library)

```javascript
const TelegramBot = require('node-telegram-bot-api');
const axios = require('axios');
const FormData = require('form-data');

// Get configuration from environment
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const COGVIDEOX_API_URL = process.env.COGVIDEOX_API_URL;
const COGVIDEOX_API_KEY = process.env.COGVIDEOX_API_KEY;

// Create bot instance
const bot = new TelegramBot(TELEGRAM_BOT_TOKEN, { polling: true });

// /start command
bot.onText(/\/start/, (msg) => {
  const chatId = msg.chat.id;
  bot.sendMessage(chatId,
    "👋 Welcome to CogVideoX Bot!\n\n" +
    "Generate videos from text with AI.\n\n" +
    "Commands:\n" +
    "/cogvideo <prompt> - Generate a video\n" +
    "/help - Show help message\n\n" +
    "Example:\n" +
    "/cogvideo A dragon flying over a neon city at night"
  );
});

// /help command
bot.onText(/\/help/, (msg) => {
  const chatId = msg.chat.id;
  bot.sendMessage(chatId,
    "🎬 CogVideoX Bot Help\n\n" +
    "📝 How to use:\n" +
    "/cogvideo <your prompt> - Generate a video from text\n\n" +
    "💡 Tips:\n" +
    "- Be descriptive with your prompts\n" +
    "- Videos take ~60 seconds to generate\n" +
    "- Each video is 13 frames at 8 FPS\n\n" +
    "📋 Examples:\n" +
    "• /cogvideo A golden retriever playing in a sunny garden\n" +
    "• /cogvideo A spaceship landing on Mars with dust clouds\n" +
    "• /cogvideo Ocean waves crashing on a beach at sunset"
  );
});

// /cogvideo command
bot.onText(/\/cogvideo (.+)/, async (msg, match) => {
  const chatId = msg.chat.id;
  const prompt = match[1];

  // Send initial status message
  const statusMsg = await bot.sendMessage(chatId,
    `🎬 Generating video...\n` +
    `📝 Prompt: ${prompt}\n\n` +
    `⏳ This will take about 60 seconds...`
  );

  try {
    const startTime = Date.now();

    // Make API request
    const response = await axios.post(
      COGVIDEOX_API_URL,
      {
        prompt: prompt,
        frames: 13,
        fps: 8,
        steps: 15
      },
      {
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': COGVIDEOX_API_KEY
        },
        timeout: 180000 // 3 minutes
      }
    );

    const result = response.data;
    const elapsedTime = (Date.now() - startTime) / 1000;

    if (result.status !== 'ok') {
      await bot.editMessageText(
        `❌ Video generation failed:\n${result.error}`,
        { chat_id: chatId, message_id: statusMsg.message_id }
      );
      return;
    }

    // Update status
    await bot.editMessageText(
      `✅ Video generated successfully!\n` +
      `⏱️ Generation time: ${(result.ms / 1000).toFixed(1)}s\n` +
      `📥 Downloading video...`,
      { chat_id: chatId, message_id: statusMsg.message_id }
    );

    // Download video
    const videoResponse = await axios.get(result.video_url, {
      responseType: 'arraybuffer',
      timeout: 60000
    });

    // Send video to user
    await bot.sendVideo(chatId, Buffer.from(videoResponse.data), {
      caption: `🎬 Generated video\n📝 Prompt: ${prompt}\n⏱️ Generated in ${(result.ms / 1000).toFixed(1)}s`
    });

    // Delete status message
    await bot.deleteMessage(chatId, statusMsg.message_id);

  } catch (error) {
    console.error('Error:', error);

    let errorMessage = '❌ An error occurred.';

    if (error.code === 'ECONNABORTED') {
      errorMessage = '❌ Request timed out. The GPU server might be overloaded.\nPlease try again in a few minutes.';
    } else if (error.response) {
      errorMessage = `❌ API request failed: ${error.response.status}`;
    } else if (error.message) {
      errorMessage = `❌ Error: ${error.message}`;
    }

    await bot.editMessageText(errorMessage, {
      chat_id: chatId,
      message_id: statusMsg.message_id
    });
  }
});

console.log('🤖 Bot is running...');
```

---

## Step 3: Install Required Dependencies

### For Python Bot

Add to `requirements.txt` or install via Replit packages:

```txt
python-telegram-bot==20.7
requests==2.31.0
```

Or in Replit Shell:
```bash
pip install python-telegram-bot requests
```

### For Node.js Bot

Add to `package.json` or install via Replit packages:

```json
{
  "dependencies": {
    "node-telegram-bot-api": "^0.64.0",
    "axios": "^1.6.0",
    "form-data": "^4.0.0"
  }
}
```

Or in Replit Shell:
```bash
npm install node-telegram-bot-api axios form-data
```

---

## Step 4: Test Your Setup

1. **Start your Replit bot** by clicking the "Run" button

2. **Open Telegram** and find your bot

3. **Test the connection**:
   - Send: `/start`
   - You should see the welcome message

4. **Generate a test video**:
   - Send: `/cogvideo A cute cat playing with a ball`
   - Wait ~60 seconds
   - You should receive the generated video

---

## Step 5: Verify API Connection

If the bot doesn't work, verify the API is reachable from Replit:

### Test from Replit Shell

```bash
# Test health endpoint
curl http://proxy.us-ca-6.gpu-instance.novita.ai:8080/health

# Test video generation
curl -X POST http://proxy.us-ca-6.gpu-instance.novita.ai:8080/generate_video \
  -H "Content-Type: application/json" \
  -H "x-api-key: 3b8cae05212822b0c5f2166719d6d7a1cc568f53af023292cdb19aedaafccf43" \
  -d '{"prompt": "test video", "frames": 13, "fps": 8, "steps": 15}'
```

Expected response:
```json
{
  "status": "ok",
  "video_path": "/tmp/videos/video_xxxxx.mp4",
  "video_url": "http://proxy.us-ca-6.gpu-instance.novita.ai:8080/videos/video_xxxxx.mp4",
  "ms": 60000,
  "frames": 13,
  "fps": 8,
  "steps": 15
}
```

---

## Troubleshooting

### Problem: "API authentication failed"

**Solution**: Double-check that `COGVIDEOX_API_KEY` secret matches exactly:
```
3b8cae05212822b0c5f2166719d6d7a1cc568f53af023292cdb19aedaafccf43
```

### Problem: "Request timed out"

**Possible causes**:
1. GPU server is processing another video (it can only handle one at a time)
2. Network connectivity issues
3. Model needs to be reloaded (first request after restart takes longer)

**Solutions**:
- Wait a few minutes and try again
- Check GPU server status: `curl http://proxy.us-ca-6.gpu-instance.novita.ai:8080/health`
- Restart the GPU server if needed

### Problem: "Network error" or "Connection refused"

**Possible causes**:
1. GPU server is down
2. Port 8080 is not accessible
3. URL is incorrect

**Solutions**:
- Verify server is running on Novita GPU
- Check the URL in your secrets matches exactly
- Test with curl from Replit shell

### Problem: Video generation works but download fails

**Possible causes**:
1. Video file was cleaned up too quickly
2. Network issue downloading the video

**Solutions**:
- Bot should display the video URL so users can download manually
- Increase timeout for video download requests

---

## Advanced Configuration

### Customize Video Parameters

You can adjust these parameters in the API call:

```python
payload = {
    "prompt": prompt,
    "frames": 13,        # Number of frames (1-49, lower = faster, less VRAM)
    "fps": 8,            # Frames per second (1-60)
    "steps": 15,         # Inference steps (1-50, lower = faster but lower quality)
    "guidance_scale": 6.0  # How closely to follow prompt (1.0-20.0)
}
```

**For faster generation** (but lower quality):
- frames: 9
- steps: 10

**For higher quality** (but slower, more VRAM):
- frames: 16
- steps: 20

**Note**: The GPU has 24GB VRAM. If you get out-of-memory errors, reduce frames and steps.

### Add Rate Limiting

To prevent abuse, add rate limiting to your bot:

```python
from collections import defaultdict
from datetime import datetime, timedelta

# Track user requests
user_requests = defaultdict(list)
MAX_REQUESTS_PER_HOUR = 5

async def cogvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Check rate limit
    now = datetime.now()
    user_requests[user_id] = [
        req_time for req_time in user_requests[user_id]
        if now - req_time < timedelta(hours=1)
    ]

    if len(user_requests[user_id]) >= MAX_REQUESTS_PER_HOUR:
        await update.message.reply_text(
            f"⚠️ Rate limit exceeded.\n"
            f"You can only generate {MAX_REQUESTS_PER_HOUR} videos per hour.\n"
            f"Please try again later."
        )
        return

    user_requests[user_id].append(now)

    # Continue with video generation...
```

### Add Logging

Track bot usage:

```python
import logging

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def cogvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    prompt = " ".join(context.args)

    logger.info(f"User {user.id} ({user.username}) requested video: {prompt}")

    # Continue with video generation...
```

---

## Cost Considerations

### GPU Server Costs
- Novita GPU servers are billed by the hour
- Consider stopping the server when not in use
- Each video takes ~60 seconds to generate

### Optimization Tips
1. **Lower default parameters**: Use frames=9, steps=10 for faster/cheaper generation
2. **Add cooldown periods**: Limit requests per user
3. **Queue system**: Handle multiple requests sequentially instead of rejecting them

---

## Example Complete Bot (Python)

Here's a production-ready example with all features:

```python
import os
import requests
import time
import logging
from datetime import datetime, timedelta
from collections import defaultdict
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

# Rate limiting
user_requests = defaultdict(list)
MAX_REQUESTS_PER_HOUR = 5

async def check_rate_limit(user_id: int) -> bool:
    """Check if user has exceeded rate limit"""
    now = datetime.now()
    user_requests[user_id] = [
        req_time for req_time in user_requests[user_id]
        if now - req_time < timedelta(hours=1)
    ]
    return len(user_requests[user_id]) < MAX_REQUESTS_PER_HOUR

async def cogvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate video from text prompt"""
    user = update.effective_user

    # Check rate limit
    if not await check_rate_limit(user.id):
        await update.message.reply_text(
            f"⚠️ Rate limit exceeded.\n"
            f"You can only generate {MAX_REQUESTS_PER_HOUR} videos per hour.\n"
            f"Please try again later."
        )
        return

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

    # Record request
    user_requests[user.id].append(datetime.now())

    # Send initial message
    status_msg = await update.message.reply_text(
        f"🎬 Generating video...\n"
        f"📝 Prompt: {prompt}\n\n"
        f"⏳ This will take about 60 seconds..."
    )

    try:
        # Make API request
        headers = {
            "Content-Type": "application/json",
            "x-api-key": COGVIDEOX_API_KEY
        }

        payload = {
            "prompt": prompt,
            "frames": 13,
            "fps": 8,
            "steps": 15
        }

        start_time = time.time()
        response = requests.post(
            COGVIDEOX_API_URL,
            headers=headers,
            json=payload,
            timeout=180
        )

        elapsed_time = int(time.time() - start_time)

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

        # Download and send video
        video_url = result.get("video_url")
        generation_time = result.get("ms", 0) / 1000

        await status_msg.edit_text(
            f"✅ Video generated!\n"
            f"⏱️ Time: {generation_time:.1f}s\n"
            f"📥 Downloading..."
        )

        video_response = requests.get(video_url, timeout=60)

        if video_response.status_code == 200:
            await update.message.reply_video(
                video=video_response.content,
                caption=f"🎬 Generated video\n📝 {prompt}\n⏱️ {generation_time:.1f}s",
                filename=f"cogvideo_{int(time.time())}.mp4"
            )
            await status_msg.delete()
            logger.info(f"Successfully sent video to user {user.id}")
        else:
            await status_msg.edit_text(
                f"✅ Generated but download failed.\n"
                f"Access here: {video_url}"
            )

    except requests.exceptions.Timeout:
        await status_msg.edit_text(
            "❌ Request timed out.\n"
            "The GPU server might be busy. Try again in a few minutes."
        )
        logger.error("Request timed out")
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
        "- Takes ~60 seconds\n"
        "- 13 frames @ 8 FPS\n\n"
        f"⚠️ Limit: {MAX_REQUESTS_PER_HOUR} videos/hour\n\n"
        "Examples:\n"
        "• /cogvideo A sunset over ocean waves\n"
        "• /cogvideo A cat playing with yarn\n"
        "• /cogvideo Fireworks in the night sky"
    )

def main():
    """Start the bot"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cogvideo", cogvideo))

    logger.info("🤖 Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
```

---

## Security Best Practices

1. **Never commit secrets**: Always use Replit Secrets, never hardcode API keys
2. **Rate limiting**: Implement per-user rate limits to prevent abuse
3. **Input validation**: Sanitize and validate user prompts
4. **Error handling**: Don't expose internal errors to users
5. **Logging**: Log all requests for monitoring and debugging

---

## Monitoring and Maintenance

### Check GPU Server Health

Add a command to check server status:

```python
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check API server status"""
    try:
        response = requests.get(
            "http://proxy.us-ca-6.gpu-instance.novita.ai:8080/health",
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

# Add to handlers
application.add_handler(CommandHandler("status", status))
```

---

## Summary

You now have everything needed to connect your Telegram bot to the CogVideoX API:

1. ✅ GPU Server running at `proxy.us-ca-6.gpu-instance.novita.ai:8080`
2. ✅ API Key: `3b8cae05212822b0c5f2166719d6d7a1cc568f53af023292cdb19aedaafccf43`
3. ✅ Complete bot code with error handling
4. ✅ Rate limiting and security measures
5. ✅ Monitoring and debugging tools

**Next Steps**:
1. Copy the bot code to your Replit project
2. Add the secrets (API URL and API Key)
3. Install dependencies
4. Run and test!

Need help? Check the troubleshooting section or verify the API is accessible from Replit using curl.
