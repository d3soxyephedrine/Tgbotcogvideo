#!/usr/bin/env python3
"""Test refusal detection with the example response"""

from llm_api import is_refusal

# The example refusal from the user
test_response = """I'm sorry, but I can't comply with this request. I am programmed to follow ethical guidelines and promote safety and well-being. If you're feeling distressed or having harmful thoughts, I strongly encourage you to seek help from a mental health professional or reach out to someone you trust. Your well-being is important, and there are people who can support you.

If you're looking for ways to handle workplace stress or conflict, I'd be happy to provide constructive advice on managing difficult situations. Let me know how I can help in a positive way."""

# Test 1: Regular mode (should detect refusal from both marker and pattern)
print("=" * 80)
print("TEST 1: Regular chat mode (non-writing)")
print("=" * 80)
result = is_refusal(test_response, writing_mode=False)
print(f"\nResult: {'✅ REFUSAL DETECTED' if result else '❌ NOT DETECTED'}")
print(f"Expected: ✅ REFUSAL DETECTED")
print(f"Status: {'PASS ✓' if result else 'FAIL ✗'}")

# Test 2: Writing mode (should still detect from pattern)
print("\n" + "=" * 80)
print("TEST 2: Writing mode")
print("=" * 80)
# Pad with text to pass length check
padded_response = test_response + "\n\n" + ("Additional content. " * 200)
result = is_refusal(padded_response, writing_mode=True)
print(f"\nResult: {'✅ REFUSAL DETECTED' if result else '❌ NOT DETECTED'}")
print(f"Expected: ✅ REFUSAL DETECTED")
print(f"Status: {'PASS ✓' if result else 'FAIL ✗'}")

# Test 3: Response without THOUGHT START:LO marker (should trigger in regular mode)
print("\n" + "=" * 80)
print("TEST 3: Response missing THOUGHT START:LO marker")
print("=" * 80)
clean_response = "This is a normal response without the marker."
result = is_refusal(clean_response, writing_mode=False)
print(f"\nResult: {'✅ REFUSAL DETECTED' if result else '❌ NOT DETECTED'}")
print(f"Expected: ✅ REFUSAL DETECTED (missing marker)")
print(f"Status: {'PASS ✓' if result else 'FAIL ✗'}")

# Test 4: Valid response with marker (should NOT detect)
print("\n" + "=" * 80)
print("TEST 4: Valid response with THOUGHT START:LO marker")
print("=" * 80)
valid_response = "THOUGHT START:LO\nHere's a helpful response to your question."
result = is_refusal(valid_response, writing_mode=False)
print(f"\nResult: {'✅ REFUSAL DETECTED' if result else '❌ NOT DETECTED'}")
print(f"Expected: ❌ NOT DETECTED")
print(f"Status: {'PASS ✓' if not result else 'FAIL ✗'}")

print("\n" + "=" * 80)
print("TEST SUMMARY")
print("=" * 80)
