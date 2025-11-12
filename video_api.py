"""
Video Generation Module
Handles AI video generation via Novita AI CogVideoX-5B API
"""

import os
import requests
import logging
import time
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)

NOVITA_API_KEY = os.getenv("NOVITA_API_KEY", "")
NOVITA_TXT2VIDEO_ENDPOINT = "https://api.novita.ai/v3/async/txt2video"
NOVITA_TASK_RESULT_ENDPOINT = "https://api.novita.ai/v3/async/task-result"
VIDEO_CREDIT_COST = 50

class VideoGenerationError(Exception):
    """Custom exception for video generation failures"""
    pass

def check_video_api_health() -> bool:
    """
    Check if Novita AI video generation API is accessible.
    Returns True if API key is configured, False otherwise.
    """
    if not NOVITA_API_KEY:
        logger.error("NOVITA_API_KEY not configured")
        return False
    return True

def _poll_task_result(task_id: str, max_wait_seconds: int = 180) -> Dict:
    """
    Poll Novita AI for task completion.
    
    Args:
        task_id: Task ID returned from submit request
        max_wait_seconds: Maximum time to wait (default 180s = 3 minutes)
    
    Returns:
        Dict with task result or error
    """
    if not NOVITA_API_KEY:
        raise VideoGenerationError("NOVITA_API_KEY not configured")
    
    headers = {
        "Authorization": f"Bearer {NOVITA_API_KEY}",
        "Content-Type": "application/json"
    }
    
    start_time = time.time()
    poll_interval = 3  # Start with 3 second intervals
    
    while True:
        elapsed = time.time() - start_time
        
        if elapsed > max_wait_seconds:
            raise VideoGenerationError(f"Video generation timed out after {max_wait_seconds}s")
        
        try:
            response = requests.get(
                NOVITA_TASK_RESULT_ENDPOINT,
                params={"task_id": task_id},
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            result = response.json()
            
            task_status = result.get("task", {}).get("status")
            
            if task_status == "TASK_STATUS_SUCCEED":
                logger.info(f"Task {task_id} completed successfully after {elapsed:.1f}s")
                return result
            elif task_status == "TASK_STATUS_FAILED":
                error_msg = result.get("task", {}).get("reason", "Unknown error")
                raise VideoGenerationError(f"Task failed: {error_msg}")
            elif task_status in ["TASK_STATUS_QUEUED", "TASK_STATUS_PROCESSING"]:
                logger.debug(f"Task {task_id} still processing... ({elapsed:.1f}s elapsed)")
                time.sleep(poll_interval)
                poll_interval = min(poll_interval * 1.2, 10)  # Exponential backoff, max 10s
            else:
                logger.warning(f"Unknown task status: {task_status}")
                time.sleep(poll_interval)
                
        except requests.RequestException as e:
            logger.warning(f"Poll request failed: {e}, retrying...")
            time.sleep(poll_interval)

def generate_video(
    prompt: str,
    frames: int = 48,
    fps: int = 8,
    steps: int = 50,
    seed: Optional[int] = None,
    width: int = 720,
    height: int = 480,
    guidance_scale: float = 6.0
) -> Dict:
    """
    Generate video using Novita AI CogVideoX-5B API.
    
    Args:
        prompt: Text description of video to generate
        frames: Number of frames (1-49, default 48 for 6 seconds at 8fps)
        fps: Frames per second (default 8)
        steps: Inference steps (1-50, default 50 for best quality)
        seed: Random seed for reproducibility (optional)
        width: Video width in pixels (default 720)
        height: Video height in pixels (default 480)
        guidance_scale: How closely to follow the prompt (1.0-20.0, default 6.0)
    
    Returns:
        Dict with keys:
        - status: "ok" or "error"
        - video_url: URL to download generated video (if ok)
        - generation_time_ms: Time taken in milliseconds (if ok)
        - error: Error message (if error)
    
    Raises:
        VideoGenerationError: If API request fails
    """
    if not NOVITA_API_KEY:
        raise VideoGenerationError("NOVITA_API_KEY not configured. Check Replit Secrets.")
    
    if not prompt or not prompt.strip():
        raise VideoGenerationError("Prompt cannot be empty")
    
    if len(prompt) > 1000:
        raise VideoGenerationError("Prompt too long (max 1000 characters)")
    
    try:
        logger.info(f"Submitting video generation: '{prompt[:50]}...'")
        
        headers = {
            "Authorization": f"Bearer {NOVITA_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model_name": "cogvideox-5b",
            "prompts": [
                {
                    "frames": frames,
                    "prompt": prompt
                }
            ],
            "width": width,
            "height": height,
            "steps": steps,
            "guidance_scale": guidance_scale,
            "extra": {
                "response_video_type": "mp4"
            }
        }
        
        if seed is not None:
            payload["seed"] = seed
        
        start_time = time.time()
        
        response = requests.post(
            NOVITA_TXT2VIDEO_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=30
        )
        
        response.raise_for_status()
        submit_result = response.json()
        
        task_id = submit_result.get("task_id")
        if not task_id:
            raise VideoGenerationError(f"No task_id in response: {submit_result}")
        
        logger.info(f"Task submitted successfully: {task_id}")
        
        task_result = _poll_task_result(task_id, max_wait_seconds=180)
        
        videos = task_result.get("videos", [])
        if not videos or len(videos) == 0:
            raise VideoGenerationError("No video in task result")
        
        video_url = videos[0].get("video_url")
        if not video_url:
            raise VideoGenerationError("No video_url in task result")
        
        elapsed_ms = int((time.time() - start_time) * 1000)
        
        logger.info(f"Video generated successfully in {elapsed_ms/1000:.1f}s")
        
        return {
            "status": "ok",
            "video_url": video_url,
            "generation_time_ms": elapsed_ms
        }
        
    except requests.Timeout:
        raise VideoGenerationError("Video submission timed out")
    except requests.RequestException as e:
        raise VideoGenerationError(f"API request failed: {str(e)}")
    except Exception as e:
        raise VideoGenerationError(f"Unexpected error: {str(e)}")

def download_video(video_url: str) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Download generated video file from Novita AI.
    
    Args:
        video_url: URL returned from generate_video
    
    Returns:
        Tuple of (video_bytes, error_message)
        - video_bytes: MP4 file content (if successful)
        - error_message: Error description (if failed)
    """
    try:
        logger.info(f"Downloading video from Novita AI...")
        
        response = requests.get(
            video_url,
            timeout=60,
            stream=True
        )
        
        response.raise_for_status()
        
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
    
    if len(prompt) > 1000:
        return False, "Prompt too long (maximum 1000 characters)"
    
    blocked_terms = []
    prompt_lower = prompt.lower()
    for term in blocked_terms:
        if term in prompt_lower:
            return False, "Prompt contains inappropriate content"
    
    return True, None
