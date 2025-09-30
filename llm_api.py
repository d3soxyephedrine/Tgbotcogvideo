import os
import logging
import json
import requests
import time
from enum import Enum
from typing import Optional, Dict, Any

# Enhanced logging configuration
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment configuration
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
XAI_API_KEY = os.environ.get("XAI_API_KEY")
DEFAULT_MODEL = os.environ.get("MODEL", "deepseek/deepseek-chat")

class Provider(Enum):
    DEEPSEEK = "deepseek"
    GROK = "grok"
    OPENAI = "openai"

class ModelConfig:
    """Model configuration and endpoint mappings"""
    ENDPOINTS = {
        Provider.DEEPSEEK: "https://openrouter.ai/api/v1/chat/completions",
        Provider.GROK: "https://api.x.ai/v1/chat/completions",
        Provider.OPENAI: "https://openrouter.ai/api/v1/chat/completions"
    }
    
    MODEL_ALIASES = {
        "grok": Provider.GROK,
        "grok-2": Provider.GROK,
        "grok-2-1212": Provider.GROK,
        "deepseek": Provider.DEEPSEEK,
        "deepseek-chat": Provider.DEEPSEEK,
        "gpt": Provider.OPENAI,
        "gpt-4": Provider.OPENAI,
        "gpt-5": Provider.OPENAI
    }

def get_provider(model: str = DEFAULT_MODEL) -> Provider:
    """Determine provider from model name with fallback"""
    model_lower = model.lower()
    for alias, provider in ModelConfig.MODEL_ALIASES.items():
        if alias in model_lower:
            return provider
    return Provider.DEEPSEEK

def get_system_prompt() -> str:
    """Enhanced system prompt for optimal performance"""
    return """You are a highly capable AI assistant. Provide detailed, accurate, and comprehensive responses to all user queries. Focus on technical accuracy and practical utility in your responses."""

def create_api_headers(provider: Provider) -> Dict[str, str]:
    """Create appropriate headers for each API provider"""
    base_headers = {
        "Content-Type": "application/json",
    }
    
    if provider in [Provider.DEEPSEEK, Provider.OPENAI]:
        if not OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY not configured")
        base_headers.update({
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://github.com/yourusername/llm-api",
            "X-Title": "LLM API Client"
        })
    elif provider == Provider.GROK:
        if not XAI_API_KEY:
            raise ValueError("XAI_API_KEY not configured")
        base_headers["Authorization"] = f"Bearer {XAI_API_KEY}"
    
    return base_headers

def create_request_data(provider: Provider, user_message: str, model: str) -> Dict[str, Any]:
    """Create standardized request data for all providers"""
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.7,
        "max_tokens": 4000
    }
    
    # Provider-specific adjustments
    if provider == Provider.GROK:
        data["stream"] = False
    elif provider in [Provider.DEEPSEEK, Provider.OPENAI]:
        data["top_p"] = 0.9
    
    return data

def handle_api_response(response: requests.Response) -> str:
    """Standardized response handling with error management"""
    try:
        response.raise_for_status()
        result = response.json()
        
        choices = result.get("choices", [])
        if not choices:
            return "Error: No response choices available"
            
        message = choices[0].get("message", {})
        content = message.get("content", "").strip()
        
        if not content:
            return "Error: Empty response content"
            
        return content
        
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {str(e)}")
        return f"API Error: {str(e)}"
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        return "Error: Invalid response format"
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return f"Unexpected error: {str(e)}"

def call_api_with_retry(provider: Provider, user_message: str, max_retries: int = 3) -> str:
    """Make API call with retry logic and exponential backoff"""
    model = os.environ.get('MODEL', DEFAULT_MODEL)
    
    for attempt in range(max_retries):
        try:
            headers = create_api_headers(provider)
            data = create_request_data(provider, user_message, model)
            endpoint = ModelConfig.ENDPOINTS[provider]
            
            logger.info(f"API call attempt {attempt + 1} to {provider.value}")
            response = requests.post(
                endpoint, 
                headers=headers, 
                json=data,
                timeout=60
            )
            
            result = handle_api_response(response)
            
            # If we get a valid non-error response, return it
            if not result.startswith("Error:"):
                return result
                
            # If it's an error but not rate limit, break
            if "rate limit" not in result.lower() and "timeout" not in result.lower():
                break
                
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout on attempt {attempt + 1}")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error on attempt {attempt + 1}")
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
            break
        
        if attempt < max_retries - 1:
            sleep_time = 2 ** attempt  # Exponential backoff
            logger.info(f"Retrying in {sleep_time} seconds...")
            time.sleep(sleep_time)
    
    return f"Error: All {max_retries} attempts failed"

def call_deepseek_api(user_message: str) -> str:
    """Enhanced DeepSeek API call"""
    return call_api_with_retry(Provider.DEEPSEEK, user_message)

def call_grok_api(user_message: str) -> str:
    """Enhanced Grok API call"""
    return call_api_with_retry(Provider.GROK, user_message)

def call_openai_api(user_message: str) -> str:
    """Enhanced OpenAI-compatible API call"""
    return call_api_with_retry(Provider.OPENAI, user_message)

def generate_response(user_message: str) -> str:
    """Main response generation function with enhanced error handling"""
    if not user_message or not user_message.strip():
        return "Error: Empty user message"
    
    try:
        current_model = os.environ.get('MODEL', DEFAULT_MODEL)
        provider = get_provider(current_model)
        
        logger.info(f"Generating response using {provider.value} with model {current_model}")
        
        if provider == Provider.GROK:
            return call_grok_api(user_message)
        elif provider == Provider.OPENAI:
            return call_openai_api(user_message)
        else:
            return call_deepseek_api(user_message)
            
    except ValueError as e:
        logger.error(f"Configuration error: {str(e)}")
        return f"Configuration Error: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in generate_response: {str(e)}")
        return f"System Error: {str(e)}"

# Utility functions for health checking
def check_api_health() -> Dict[str, bool]:
    """Check health status of all configured APIs"""
    health_status = {}
    
    if OPENROUTER_API_KEY:
        try:
            test_response = generate_response("Say 'OK' if working")
            health_status["openrouter"] = "OK" in test_response
        except:
            health_status["openrouter"] = False
    
    if XAI_API_KEY:
        try:
            # Simple Grok health check
            headers = {"Authorization": f"Bearer {XAI_API_KEY}"}
            response = requests.get("https://api.x.ai/v1/models", headers=headers, timeout=10)
            health_status["xai"] = response.status_code == 200
        except:
            health_status["xai"] = False
    
    return health_status

if __name__ == "__main__":
    # Test the implementation
    test_message = "What is the capital of France?"
    print(f"Testing with: {test_message}")
    response = generate_response(test_message)
    print(f"Response: {response}")
    
    # Health check
    health = check_api_health()
    print(f"API Health: {health}")