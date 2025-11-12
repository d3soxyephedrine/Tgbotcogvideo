"""
Video Generation Module
Handles AI video generation via Novita CogVideoX-5B API
"""

import os
import requests
import logging
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)

# Configuration
VIDEO_API_URL = os.getenv("VIDEO_API_URL", "")
VIDEO_API_KEY = os.getenv("VIDEO_API_KEY", "")
VIDEO_CREDIT_COST = 50  # Credits to deduct per video

class VideoGenerationError(Exception):
    """Custom exception for video generation failures"""
    pass

def check_video_api_health() -> bool:
    """
    Check if video generation API is online and responding.
    Returns True if healthy, False otherwise.
    """
    try:
        response = requests.get(
            f"{VIDEO_API_URL}/health",
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        return data.get("status") == "ready"
    except Exception as e:
        logger.error(f"Video API health check failed: {e}")
        return False

def generate_video(
    prompt: str,
    frames: int = 16,
    fps: int = 8,
    steps: int = 20,
    seed: Optional[int] = None
) -> Dict:
    """
    Generate video using CogVideoX-5B API.
    
    Args:
        prompt: Text description of video to generate
        frames: Number of frames (8-24, default 16)
        fps: Frames per second (default 8)
        steps: Inference steps (default 20, more = better quality but slower)
        seed: Random seed for reproducibility (optional)
    
    Returns:
        Dict with keys:
        - status: "ok" or "error"
        - video_path: Remote path to generated video (if ok)
        - generation_time_ms: Time taken in milliseconds (if ok)
        - error: Error message (if error)
    
    Raises:
        VideoGenerationError: If API request fails
    """
    if not VIDEO_API_URL or not VIDEO_API_KEY:
        raise VideoGenerationError("Video API not configured. Check Replit Secrets.")
    
    if not prompt or not prompt.strip():
        raise VideoGenerationError("Prompt cannot be empty")
    
    if len(prompt) > 500:
        raise VideoGenerationError("Prompt too long (max 500 characters)")
    
    try:
        logger.info(f"Generating video: '{prompt[:50]}...'")
        
        response = requests.post(
            f"{VIDEO_API_URL}/generate_video",
            headers={
                "Content-Type": "application/json",
                "x-api-key": VIDEO_API_KEY
            },
            json={
                "prompt": prompt,
                "frames": frames,
                "fps": fps,
                "steps": steps,
                "seed": seed
            },
            timeout=120  # 2 minutes timeout (generation takes ~30s)
        )
        
        response.raise_for_status()
        result = response.json()
        
        if result.get("status") == "ok":
            logger.info(f"Video generated successfully in {result.get('generation_time_ms', 0)/1000:.1f}s")
        else:
            logger.error(f"Video generation failed: {result.get('error', 'Unknown error')}")
        
        return result
        
    except requests.Timeout:
        raise VideoGenerationError("Video generation timed out (>2 minutes)")
    except requests.RequestException as e:
        raise VideoGenerationError(f"API request failed: {str(e)}")
    except Exception as e:
        raise VideoGenerationError(f"Unexpected error: {str(e)}")

def download_video(video_path: str) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Download generated video file from Novita server.
    
    Args:
        video_path: Full path like "/root/video_api/videos/abc123.mp4"
    
    Returns:
        Tuple of (video_bytes, error_message)
        - video_bytes: MP4 file content (if successful)
        - error_message: Error description (if failed)
    """
    if not VIDEO_API_URL or not VIDEO_API_KEY:
        return None, "Video API not configured"
    
    try:
        # Extract filename from full path
        filename = os.path.basename(video_path)
        
        logger.info(f"Downloading video: {filename}")
        
        response = requests.get(
            f"{VIDEO_API_URL}/get_video/{filename}",
            headers={"x-api-key": VIDEO_API_KEY},
            timeout=60,
            stream=True
        )
        
        response.raise_for_status()
        
        # Read video content
        video_bytes = response.content
        logger.info(f"Downloaded video: {len(video_bytes) / 1024 / 1024:.2f} MB")
        
        return video_bytes, None
        
    except requests.RequestException as e:
        error_msg = f"Failed to download video: {str(e)}"
        logger.error(error_msg)
        return None, error_msg
    except Exception as e:
        error_msg = f"Unexpected download error: {str(e)}"
        logger.error(error_msg)
        return None, error_msg

def validate_prompt(prompt: str) -> Tuple[bool, Optional[str]]:
    """
    Validate video generation prompt.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not prompt or not prompt.strip():
        return False, "Prompt cannot be empty"
    
    if len(prompt) < 3:
        return False, "Prompt too short (minimum 3 characters)"
    
    if len(prompt) > 500:
        return False, "Prompt too long (maximum 500 characters)"
    
    # Basic content filtering (optional - customize as needed)
    blocked_terms = []  # Add any terms you want to block
    prompt_lower = prompt.lower()
    for term in blocked_terms:
        if term in prompt_lower:
            return False, "Prompt contains inappropriate content"
    
    return True, None
