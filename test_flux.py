import os
import sys
from llm_api import generate_image

print("=" * 80)
print("TESTING NOVITA AI IMAGE GENERATION WITH FLUX.1-DEV")
print("=" * 80)
print()

# Check API key
api_key = os.environ.get("NOVITA_API_KEY")
if not api_key:
    print("❌ ERROR: NOVITA_API_KEY not found")
    sys.exit(1)

print("✓ NOVITA_API_KEY is configured")
print()

# Test prompt
test_prompt = "a beautiful woman with long flowing hair, photorealistic portrait, detailed face"
print(f"Test prompt: '{test_prompt}'")
print()
print("Submitting to Novita AI (Flux.1-dev)...")
print("This may take 30-60 seconds for Flux quality...")
print()

# Generate image
result = generate_image(test_prompt)

if result.get("success"):
    print("✅ SUCCESS: Image generated!")
    print(f"Image URL: {result.get('image_url')}")
    print()
    print("You can now test via Telegram with the /imagine command")
else:
    print(f"❌ FAILED: {result.get('error')}")
    sys.exit(1)
