import os
import requests
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)

VIDEO_API_URL = os.getenv("VIDEO_API_URL")
VIDEO_API_KEY = os.getenv("VIDEO_API_KEY")

def generate_video(prompt: str, frames: int = 16, steps: int = 20) -> Dict:
    """
    Generate video via Novita GPU API.
    Takes ~30 seconds.
    
    Args:
        prompt: Text description for video generation
        frames: Number of frames to generate (default: 16)
        steps: Number of diffusion steps (default: 20)
    
    Returns: 
        {"status": "ok", "video_path": "/root/.../xyz.mp4", "generation_time_ms": 28000}
        or {"status": "error", "error": "message"}
    """
    if not VIDEO_API_URL:
        logger.error("VIDEO_API_URL not configured")
        return {"status": "error", "error": "Video API URL not configured"}
    
    if not VIDEO_API_KEY:
        logger.error("VIDEO_API_KEY not configured")
        return {"status": "error", "error": "Video API key not configured"}
    
    try:
        response = requests.post(
            f"{VIDEO_API_URL}/generate_video",
            headers={
                "Content-Type": "application/json",
                "x-api-key": VIDEO_API_KEY
            },
            json={
                "prompt": prompt,
                "frames": frames,
                "fps": 8,
                "steps": steps
            },
            timeout=90
        )
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        logger.error("Video generation timed out")
        return {"status": "error", "error": "Video generation timed out (>90s)"}
    except requests.ConnectionError as e:
        logger.error(f"Video generation connection failed: {e}")
        return {"status": "error", "error": "Could not connect to video generation server"}
    except Exception as e:
        logger.error(f"Video generation failed: {e}")
        return {"status": "error", "error": str(e)}

def download_video(video_path: str) -> Optional[bytes]:
    """
    Download generated video file from Novita server.
    
    Args:
        video_path: Full path like "/root/video_api/videos/abc123.mp4"
    
    Returns:
        Video bytes or None if failed
    """
    if not VIDEO_API_URL:
        logger.error("VIDEO_API_URL not configured")
        return None
    
    if not VIDEO_API_KEY:
        logger.error("VIDEO_API_KEY not configured")
        return None
    
    try:
        # Extract filename from path
        filename = os.path.basename(video_path)
        
        response = requests.get(
            f"{VIDEO_API_URL}/get_video/{filename}",
            headers={"x-api-key": VIDEO_API_KEY},
            timeout=30
        )
        response.raise_for_status()
        return response.content
    except Exception as e:
        logger.error(f"Video download failed: {e}")
        return None
