import os
import requests
from typing import Optional, Dict, Tuple
import logging

logger = logging.getLogger(__name__)

VIDEO_API_URL = os.getenv("VIDEO_API_URL")
VIDEO_API_KEY = os.getenv("VIDEO_API_KEY")

def check_video_api_health() -> Tuple[bool, str]:
    """
    Check if the VIDEO API server is accessible and healthy.
    
    Returns:
        (is_healthy, message) tuple
    """
    if not VIDEO_API_URL:
        return False, "VIDEO_API_URL environment variable not configured"
    
    if not VIDEO_API_KEY:
        return False, "VIDEO_API_KEY environment variable not configured"
    
    try:
        response = requests.get(
            f"{VIDEO_API_URL}/health",
            timeout=5
        )
        if response.status_code == 200:
            return True, f"GPU server is healthy at {VIDEO_API_URL}"
        else:
            return False, f"GPU server responded with status {response.status_code}"
    except requests.Timeout:
        return False, f"GPU server at {VIDEO_API_URL} timed out (not responding within 5s)"
    except requests.ConnectionError:
        return False, f"Cannot connect to GPU server at {VIDEO_API_URL} - server may be down or URL incorrect"
    except Exception as e:
        return False, f"GPU server health check failed: {str(e)}"

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
        logger.info(f"Calling VIDEO_API at {VIDEO_API_URL}/generate_video")
        logger.debug(f"Request: prompt='{prompt[:50]}...', frames={frames}, steps={steps}")
        
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
        
        result = response.json()
        logger.info(f"VIDEO_API response: {result.get('status', 'unknown')}")
        return result
        
    except requests.Timeout:
        error_msg = f"Video generation timed out after 90s. GPU server at {VIDEO_API_URL} may be overloaded or down."
        logger.error(error_msg)
        return {"status": "error", "error": error_msg}
    except requests.ConnectionError as e:
        error_msg = f"Cannot connect to GPU server at {VIDEO_API_URL}. Server may be down. Error: {str(e)}"
        logger.error(error_msg)
        return {"status": "error", "error": "GPU server is not accessible. Please contact support."}
    except requests.HTTPError as e:
        error_msg = f"HTTP error from VIDEO_API: {e.response.status_code} - {e.response.text}"
        logger.error(error_msg)
        return {"status": "error", "error": f"Video generation failed with HTTP {e.response.status_code}"}
    except Exception as e:
        logger.error(f"Video generation failed: {type(e).__name__}: {str(e)}")
        return {"status": "error", "error": f"Unexpected error: {str(e)}"}

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
        
        logger.info(f"Video download started from: /get_video/{filename}")
        
        response = requests.get(
            f"{VIDEO_API_URL}/get_video/{filename}",
            headers={"x-api-key": VIDEO_API_KEY},
            timeout=30
        )
        response.raise_for_status()
        
        video_bytes = response.content
        logger.info(f"Video downloaded successfully: {len(video_bytes)} bytes")
        return video_bytes
        
    except requests.Timeout:
        logger.error(f"Video download timed out for {filename}")
        return None
    except requests.ConnectionError as e:
        logger.error(f"Video download connection failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Video download failed: {type(e).__name__}: {str(e)}")
        return None
