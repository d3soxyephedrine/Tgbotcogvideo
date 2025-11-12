#!/bin/bash
# Quick deployment script for CogVideoX on Novita.ai
# Run this ON YOUR GPU SERVER after SSH'ing in

set -e

echo "🚀 CogVideoX Quick Deploy"
echo "========================="

# Step 1: Install dependencies
echo "📦 Installing Python dependencies..."
pip install -q fastapi uvicorn python-dotenv torch diffusers transformers accelerate

# Step 2: Create .env file
echo "⚙️ Creating .env configuration..."
cat > .env << 'ENVEOF'
API_SECRET=your-secret-key-change-this
SERVER_HOST=proxy.us-dallas-nas-2.gpu-instance.novita.ai:8080
MODEL_ID=THUDM/CogVideoX-5b
DEFAULT_FRAMES=49
DEFAULT_FPS=8
MAX_FRAMES=49
OUTPUT_DIR=/root/videos
ENVEOF

# Step 3: Create videos directory
mkdir -p /root/videos
echo "✅ Created videos directory"

# Step 4: Create main.py
echo "📝 Creating main.py..."
cat > main.py << 'PYEOF'
"""
FastAPI Video Generation Service using CogVideoX-5B
Runs on GPU server, exposes POST /generate_video endpoint
"""
import os
import time
import torch
import uuid
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator
from typing import Optional
from dotenv import load_dotenv
from diffusers import CogVideoXPipeline
from diffusers.utils import export_to_video
import logging

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from environment
API_SECRET = os.getenv("API_SECRET", "change-this-secret-key-12345")
MODEL_ID = os.getenv("MODEL_ID", "THUDM/CogVideoX-5b")
DEFAULT_FRAMES = int(os.getenv("DEFAULT_FRAMES", "16"))
DEFAULT_FPS = int(os.getenv("DEFAULT_FPS", "8"))
DEFAULT_STEPS = int(os.getenv("DEFAULT_STEPS", "20"))
MAX_FRAMES = int(os.getenv("MAX_FRAMES", "49"))
MAX_STEPS = int(os.getenv("MAX_STEPS", "50"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/root/videos")

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Global pipeline - loaded once on startup
pipeline = None
device_info = {}

app = FastAPI(
    title="CogVideoX Video Generation API",
    description="GPU-accelerated video generation using CogVideoX-5B",
    version="1.0.0"
)

# Mount static files for video downloads
app.mount("/videos", StaticFiles(directory=OUTPUT_DIR), name="videos")

class VideoRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1000, description="Text prompt for video generation")
    frames: Optional[int] = Field(DEFAULT_FRAMES, ge=1, le=MAX_FRAMES, description=f"Number of frames (1-{MAX_FRAMES})")
    fps: Optional[int] = Field(DEFAULT_FPS, ge=1, le=60, description="Frames per second (1-60)")
    steps: Optional[int] = Field(DEFAULT_STEPS, ge=1, le=MAX_STEPS, description=f"Inference steps (1-{MAX_STEPS})")
    guidance_scale: Optional[float] = Field(6.0, ge=1.0, le=20.0, description="Guidance scale (1.0-20.0)")
    
    @validator('prompt')
    def validate_prompt(cls, v):
        if not v or not v.strip():
            raise ValueError('Prompt cannot be empty')
        return v.strip()

class VideoResponse(BaseModel):
    status: str
    video_path: Optional[str] = None
    video_url: Optional[str] = None
    ms: Optional[int] = None
    error: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    model_id: str
    gpu_name: str
    cuda_available: bool
    model_loaded: bool

async def verify_api_key(x_api_key: str = Header(...)):
    """Verify API key from header"""
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

@app.on_event("startup")
async def load_model():
    """Load CogVideoX pipeline on startup"""
    global pipeline, device_info
    
    server_host = os.getenv("SERVER_HOST", "localhost:8080")
    if server_host == "localhost:8080":
        logger.warning("⚠️ SERVER_HOST not configured! Video URLs may not work.")
    else:
        logger.info(f"✓ SERVER_HOST: {server_host}")
    
    try:
        logger.info("🚀 Loading CogVideoX pipeline...")
        logger.info(f"Model: {MODEL_ID}")
        
        cuda_available = torch.cuda.is_available()
        
        if cuda_available:
            gpu_name = torch.cuda.get_device_name(0)
            logger.info(f"✓ GPU: {gpu_name}")
            device_info = {"gpu_name": gpu_name, "cuda_available": True}
        else:
            logger.warning("⚠ CUDA not available")
            device_info = {"gpu_name": "N/A", "cuda_available": False}
        
        pipeline = CogVideoXPipeline.from_pretrained(
            MODEL_ID,
            torch_dtype=torch.float16 if cuda_available else torch.float32
        )
        
        if cuda_available:
            pipeline.to("cuda")
            pipeline.enable_model_cpu_offload()
        
        logger.info("✅ Pipeline ready")
        
    except Exception as e:
        logger.error(f"❌ Failed to load: {str(e)}")
        raise

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="ok" if pipeline else "model_not_loaded",
        model_id=MODEL_ID,
        gpu_name=device_info.get("gpu_name", "N/A"),
        cuda_available=device_info.get("cuda_available", False),
        model_loaded=pipeline is not None
    )

@app.post("/generate_video", response_model=VideoResponse)
async def generate_video(
    request: VideoRequest,
    api_key: str = Depends(verify_api_key)
):
    """Generate video from text prompt"""
    if not pipeline:
        return VideoResponse(status="error", error="Model not loaded")
    
    start_time = time.time()
    
    try:
        logger.info(f"📹 Prompt: '{request.prompt[:50]}...'")
        
        video_frames = pipeline(
            prompt=request.prompt,
            num_frames=request.frames,
            num_inference_steps=request.steps,
            guidance_scale=request.guidance_scale,
            generator=torch.Generator().manual_seed(int(time.time()))
        ).frames[0]
        
        # Random UUID filename for security
        timestamp = int(time.time() * 1000)
        random_id = str(uuid.uuid4())[:8]
        output_filename = f"video_{timestamp}_{random_id}.mp4"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        
        export_to_video(video_frames, output_path, fps=request.fps)
        
        elapsed_ms = int((time.time() - start_time) * 1000)
        
        server_host = os.getenv("SERVER_HOST", "localhost:8080")
        video_url = f"http://{server_host}/videos/{output_filename}"
        
        logger.info(f"✅ Done: {video_url} ({elapsed_ms}ms)")
        
        return VideoResponse(
            status="ok",
            video_path=output_path,
            video_url=video_url,
            ms=elapsed_ms
        )
        
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error(f"❌ Failed: {str(e)}")
        return VideoResponse(status="error", error=str(e), ms=elapsed_ms)

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "CogVideoX Video Generation API",
        "model": MODEL_ID,
        "status": "running"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
PYEOF

echo "✅ Files created successfully!"
echo ""
echo "⚙️ IMPORTANT: Edit .env and set your API_SECRET"
echo "   nano .env"
echo ""
echo "🚀 To start the server:"
echo "   nohup python main.py > server.log 2>&1 &"
echo ""
echo "📊 To check status:"
echo "   tail -f server.log"
echo "   curl http://localhost:8080/health"
