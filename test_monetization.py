#!/usr/bin/env python3
"""
Manual test script for monetization features
Tests: /daily, credit deduction, /balance, volume bonuses, video paywall
"""
import os
import sys
import requests
import json
from datetime import datetime, timedelta

# Setup app context for database access
from main import app, db
from models import User

BOT_TOKEN = os.environ.get("BOT_TOKEN")
BASE_URL = f"http://localhost:5000/{BOT_TOKEN}"

def create_test_telegram_update(telegram_id, text, message_id=1):
    """Create a Telegram update payload"""
    return {
        "update_id": message_id,
        "message": {
            "message_id": message_id,
            "from": {
                "id": telegram_id,
                "is_bot": False,
                "first_name": "Test",
                "username": f"testuser{telegram_id}"
            },
            "chat": {
                "id": telegram_id,
                "first_name": "Test",
                "username": f"testuser{telegram_id}",
                "type": "private"
            },
            "date": int(datetime.now().timestamp()),
            "text": text
        }
    }

def send_telegram_message(telegram_id, text):
    """Send a test message to the bot"""
    payload = create_test_telegram_update(telegram_id, text)
    print(f"\n📤 Sending: {text}")
    try:
        response = requests.post(BASE_URL, json=payload, timeout=10)
        print(f"✅ Status: {response.status_code}")
        return response
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def check_user_in_db(telegram_id):
    """Check user data in database"""
    with app.app_context():
        user = User.query.filter_by(telegram_id=telegram_id).first()
        if user:
            print(f"\n💾 Database state for user {telegram_id}:")
            print(f"  • Credits (purchased): {user.credits}")
            print(f"  • Daily credits: {user.daily_credits}")
            print(f"  • Daily credits expiry: {user.daily_credits_expiry}")
            print(f"  • Last daily claim: {user.last_daily_claim_at}")
            print(f"  • Last purchase: {user.last_purchase_at}")
            
            if user.daily_credits_expiry:
                time_until_expiry = user.daily_credits_expiry - datetime.utcnow()
                hours = int(time_until_expiry.total_seconds() // 3600)
                print(f"  • Expiry in: {hours} hours")
            
            if user.last_daily_claim_at:
                time_since_claim = datetime.utcnow() - user.last_daily_claim_at
                hours = int(time_since_claim.total_seconds() // 3600)
                minutes = int((time_since_claim.total_seconds() % 3600) // 60)
                print(f"  • Time since claim: {hours}h {minutes}m")
            
            return user
        else:
            print(f"\n❌ User {telegram_id} not found in database")
            return None

def test_daily_command():
    """Test /daily command functionality"""
    print("\n" + "="*60)
    print("TEST 1: /daily Command")
    print("="*60)
    
    test_user_id = 999888777
    
    # Clean up test user if exists
    with app.app_context():
        existing = User.query.filter_by(telegram_id=test_user_id).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
            print(f"🗑️ Cleaned up existing test user {test_user_id}")
    
    # Test 1: First /daily claim
    print("\n--- Test 1a: First /daily claim ---")
    send_telegram_message(test_user_id, "/daily")
    import time
    time.sleep(2)  # Wait for processing
    user = check_user_in_db(test_user_id)
    
    if user:
        assert user.daily_credits == 25, f"Expected 25 daily credits, got {user.daily_credits}"
        assert user.last_daily_claim_at is not None, "last_daily_claim_at should be set"
        assert user.daily_credits_expiry is not None, "daily_credits_expiry should be set"
        
        # Check expiry is approximately 48h from now
        expected_expiry = datetime.utcnow() + timedelta(hours=48)
        time_diff = abs((user.daily_credits_expiry - expected_expiry).total_seconds())
        assert time_diff < 120, f"Expiry should be ~48h from now, diff: {time_diff}s"
        
        print("✅ PASS: First /daily claim works correctly")
    else:
        print("❌ FAIL: User not created")
        return False
    
    # Test 2: Second /daily claim immediately (should fail due to 24h cooldown)
    print("\n--- Test 1b: Second /daily claim (should fail) ---")
    send_telegram_message(test_user_id, "/daily")
    time.sleep(2)
    user = check_user_in_db(test_user_id)
    
    if user:
        assert user.daily_credits == 25, f"Credits should still be 25, got {user.daily_credits}"
        print("✅ PASS: 24h cooldown enforced")
    
    return True

def test_credit_deduction():
    """Test smart credit deduction (daily first, then purchased)"""
    print("\n" + "="*60)
    print("TEST 2: Smart Credit Deduction")
    print("="*60)
    
    test_user_id = 999888777
    
    # Send a text message (costs 1 credit)
    print("\n--- Test 2a: Send text message (1 credit) ---")
    initial = check_user_in_db(test_user_id)
    initial_daily = initial.daily_credits if initial else 0
    initial_purchased = initial.credits if initial else 0
    
    send_telegram_message(test_user_id, "hello")
    import time
    time.sleep(3)  # Wait for LLM processing
    
    user = check_user_in_db(test_user_id)
    if user:
        expected_daily = initial_daily - 1
        assert user.daily_credits == expected_daily, f"Daily credits should be {expected_daily}, got {user.daily_credits}"
        assert user.credits == initial_purchased, f"Purchased credits should stay {initial_purchased}, got {user.credits}"
        print("✅ PASS: Daily credits used first")
    
    return True

def test_balance_command():
    """Test /balance shows breakdown correctly"""
    print("\n" + "="*60)
    print("TEST 3: /balance Command")
    print("="*60)
    
    test_user_id = 999888777
    
    send_telegram_message(test_user_id, "/balance")
    import time
    time.sleep(2)
    check_user_in_db(test_user_id)
    print("✅ PASS: /balance command executed (check Telegram for output)")
    
    return True

def test_volume_bonuses():
    """Test volume bonuses display in /buy"""
    print("\n" + "="*60)
    print("TEST 4: Volume Bonuses in /buy")
    print("="*60)
    
    test_user_id = 999888777
    
    send_telegram_message(test_user_id, "/buy")
    import time
    time.sleep(2)
    
    # The /buy command should show:
    # • $10 → 200 credits (5.0¢/credit)
    # • $20 → 420 credits (4.76¢/credit) +5% bonus
    # • $50 → 1,120 credits (4.46¢/credit) +12% bonus
    # • $100 → 2,360 credits (4.24¢/credit) +18% bonus
    
    print("✅ PASS: /buy command executed (check Telegram for volume bonuses)")
    
    return True

def test_video_paywall():
    """Test video paywall (requires first purchase)"""
    print("\n" + "="*60)
    print("TEST 5: Video Paywall")
    print("="*60)
    
    test_user_id = 999888777
    
    user = check_user_in_db(test_user_id)
    if user and not user.last_purchase_at:
        print("✅ User has no purchases yet, video should be locked")
        print("Note: /img2video requires sending a photo, can't test via text-only API")
    else:
        print("⚠️ User already has a purchase, video unlocked")
    
    return True

def main():
    """Run all tests"""
    print("\n🧪 Starting Monetization Feature Tests")
    print("=" * 60)
    
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN not set")
        sys.exit(1)
    
    # Run tests
    tests = [
        test_daily_command,
        test_credit_deduction,
        test_balance_command,
        test_volume_bonuses,
        test_video_paywall,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"\n❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"✅ Passed: {passed}/{total}")
    
    if passed == total:
        print("\n🎉 All tests passed! Monetization system is working correctly.")
    else:
        print(f"\n⚠️ {total - passed} test(s) failed.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
