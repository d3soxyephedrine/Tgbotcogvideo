"""
Add this code to your telegram_handler.py to integrate CogVideoX GPU server

Step 1: Add these environment variables to your Replit Secrets:
- COGVIDEOX_API_URL: http://YOUR_GPU_SERVER_IP:8080/generate_video
- COGVIDEOX_API_KEY: your-super-secret-key-here (must match GPU server's API_SECRET)

Step 2: Add this import at the top of telegram_handler.py:
"""

import os
import requests
import logging

logger = logging.getLogger(__name__)

# Environment variables
COGVIDEOX_API_URL = os.getenv("COGVIDEOX_API_URL")
COGVIDEOX_API_KEY = os.getenv("COGVIDEOX_API_KEY")

def generate_cogvideox_video(prompt, frames=16, fps=8, steps=20):
    """
    Generate video using CogVideoX-5B on GPU server
    
    Args:
        prompt (str): Text description of the video
        frames (int): Number of frames (1-49)
        fps (int): Frames per second (1-60)
        steps (int): Inference steps (1-50)
    
    Returns:
        dict: {"status": "ok", "video_path": "...", "ms": 12345}
              or {"status": "error", "error": "message"}
    """
    if not COGVIDEOX_API_URL or not COGVIDEOX_API_KEY:
        return {
            "status": "error",
            "error": "CogVideoX API not configured. Contact admin."
        }
    
    try:
        logger.info(f"Calling CogVideoX GPU server: {prompt[:50]}...")
        
        response = requests.post(
            COGVIDEOX_API_URL,
            json={
                "prompt": prompt,
                "frames": frames,
                "fps": fps,
                "steps": steps
            },
            headers={
                "Content-Type": "application/json",
                "x-api-key": COGVIDEOX_API_KEY
            },
            timeout=300  # 5 minute timeout for video generation
        )
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 401:
            return {"status": "error", "error": "Invalid API key"}
        else:
            return {"status": "error", "error": f"HTTP {response.status_code}"}
    
    except requests.exceptions.Timeout:
        return {"status": "error", "error": "Video generation timed out (>5 min)"}
    except Exception as e:
        logger.error(f"CogVideoX API error: {str(e)}")
        return {"status": "error", "error": str(e)}


"""
Step 3: Add this command handler to handle_telegram_update() function
Place it near the other video generation handlers (around line 1933)
"""

# Check for /cogvideo command (CogVideoX-5B text-to-video on GPU server)
if text and (text.lower() == '/cogvideo' or text.lower().startswith('/cogvideo ')):
    # Extract prompt
    if text.lower() == '/cogvideo':
        response = """🎬 *CogVideoX-5B Video Generation* (Text-to-Video)

*Create videos from text descriptions!*

*Usage:*
`/cogvideo [your description]`

*Examples:*
• `/cogvideo A dragon flying over a neon city at night`
• `/cogvideo Waves crashing on a beach during sunset`
• `/cogvideo A robot dancing in a futuristic warehouse`

*Pricing:*
• 60 credits per video (16 frames, 8 FPS, ~2 seconds)

*Note:* This generates videos from scratch using AI on our GPU server.
For image-to-video, use `/vid` or `/img2video` instead."""
        
        send_message(chat_id, response, parse_mode="Markdown")
        return
    
    # Extract prompt after /cogvideo
    prompt = text[10:].strip()  # Remove '/cogvideo ' prefix
    
    if not prompt:
        send_message(chat_id, "❌ Please provide a description after /cogvideo")
        return
    
    logger.info(f"Processing CogVideoX video generation: {prompt[:50]}...")
    
    # Credit cost
    VIDEO_CREDITS = 60
    
    # Check if user has made first purchase
    if user.purchased_credits == 0 and user.images_generated == 0:
        send_message(
            chat_id, 
            "🔒 *Video generation requires a purchase first*\n\n"
            "To unlock video generation:\n"
            "• Use /buy to purchase credits via Telegram Stars\n"
            "• Or use /crypto for cryptocurrency payment\n\n"
            "After your first purchase, you'll have access to all video features!",
            parse_mode="Markdown"
        )
        return
    
    # Check balance upfront
    available_balance = (user.purchased_credits - user.purchased_credits_used) + (user.daily_credits - user.daily_credits_used)
    
    if available_balance < VIDEO_CREDITS:
        send_message(
            chat_id,
            f"❌ Insufficient credits!\n\n"
            f"💰 Available: {available_balance} credits\n"
            f"🎬 Video cost: {VIDEO_CREDITS} credits\n"
            f"📊 Need: {VIDEO_CREDITS - available_balance} more credits\n\n"
            f"Use /buy to purchase more credits."
        )
        return
    
    # Deduct credits upfront
    try:
        deducted = deduct_credits(user, VIDEO_CREDITS)
        if not deducted:
            send_message(chat_id, "❌ Failed to deduct credits. Please try again.")
            return
        
        logger.info(f"✓ Deducted {VIDEO_CREDITS} credits upfront for CogVideoX video")
    except Exception as e:
        logger.error(f"Error deducting credits: {str(e)}")
        send_message(chat_id, "❌ Error processing credits. Please try again.")
        return
    
    # Send processing message
    processing_msg = send_message(
        chat_id,
        f"🎬 *Generating video on GPU server...*\n\n"
        f"📝 Prompt: {prompt[:100]}\n"
        f"💰 Cost: {VIDEO_CREDITS} credits\n\n"
        f"⏳ This may take 2-5 minutes. Please wait...",
        parse_mode="Markdown"
    )
    
    try:
        # Generate video on GPU server
        result = generate_cogvideox_video(prompt=prompt)
        
        if result["status"] == "ok":
            video_path = result["video_path"]
            generation_ms = result.get("ms", 0)
            generation_sec = generation_ms / 1000
            
            logger.info(f"✅ CogVideoX video generated: {video_path} ({generation_sec:.1f}s)")
            
            # Read video file from GPU server (you'll need to transfer it)
            # For now, just send success message
            # TODO: Implement video file transfer from GPU server to bot
            
            send_message(
                chat_id,
                f"✅ *Video generated successfully!*\n\n"
                f"⏱ Generation time: {generation_sec:.1f}s\n"
                f"📁 Video saved at: `{video_path}`\n\n"
                f"💡 Note: Auto-download coming soon. For now, video is on GPU server.",
                parse_mode="Markdown"
            )
            
            # TODO: Download video from GPU server and send to user
            # You'll need to expose the video file via HTTP or implement file transfer
            
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error(f"CogVideoX video generation failed: {error_msg}")
            
            # Refund credits
            refund_credits(user, VIDEO_CREDITS)
            
            send_message(
                chat_id,
                f"❌ Video generation failed: {error_msg}\n\n"
                f"✅ {VIDEO_CREDITS} credits have been refunded to your account."
            )
    
    except Exception as e:
        logger.error(f"Error in CogVideoX video generation: {str(e)}")
        
        # Refund credits
        refund_credits(user, VIDEO_CREDITS)
        
        send_message(
            chat_id,
            f"❌ Error generating video: {str(e)}\n\n"
            f"✅ {VIDEO_CREDITS} credits have been refunded."
        )
    
    return


"""
Step 4: Add /cogvideo to the bot commands list

In main.py, find the commands list (around line 200) and add:
"""
commands.append({
    "command": "cogvideo",
    "description": "🎬 Generate video from text (CogVideoX-5B)"
})


"""
Step 5: Update the help message

In telegram_handler.py, find the /help response and add:
"""
# Add this to the help message:
🎬 *Video Generation:*
• **/cogvideo**: Generate video from text description (60 credits)
  - Example: /cogvideo A dragon flying over a neon city
• **/vid**: WAN 2.2 - Image-to-video (50-78 credits)
• **/img2video**: WAN 2.5 - Image-to-video (50 credits)


"""
IMPORTANT NOTES FOR VIDEO FILE TRANSFER:

The current implementation sends a success message but doesn't transfer the video file.
You have two options:

Option 1 (Recommended): Expose videos via HTTP
Add this to your FastAPI server (main.py):

from fastapi.staticfiles import StaticFiles
app.mount("/videos", StaticFiles(directory=OUTPUT_DIR), name="videos")

Then modify the response to include a download URL:
{
    "status": "ok",
    "video_path": "/tmp/videos/video_123.mp4",
    "video_url": f"http://YOUR_SERVER_IP:8080/videos/video_123.mp4",
    "ms": 12345
}

Then in telegram_handler.py, download and send:
if result["status"] == "ok":
    video_url = result["video_url"]
    video_response = requests.get(video_url, timeout=60)
    with open("/tmp/temp_video.mp4", "wb") as f:
        f.write(video_response.content)
    
    send_video(chat_id, "/tmp/temp_video.mp4")

Option 2: Use SCP/SFTP
Set up SSH keys and use subprocess to scp the file from GPU server to bot server.

Option 3: Use Object Storage
Upload generated videos to cloud storage (S3, etc.) and send download link.
"""
