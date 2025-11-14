#!/usr/bin/env python3
import os
from main import app, db
from models import User
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

BOT_TOKEN = os.environ.get("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

MESSAGE = """
🎮 *Join Our Discord Community!*

We've launched an official Discord server for KO2 Bot users!

🌟 *What you'll find:*
• Get help and support
• Share your creations (images, videos)
• Feature requests & suggestions  
• Community updates & announcements
• Connect with other users

🔗 *Join now:* https://discord.gg/zv8HH9YmeP

See you there! 🎉
"""

def send_message(telegram_id):
    """Send message to a single user"""
    try:
        r = requests.post(
            f"{BASE_URL}/sendMessage",
            json={"chat_id": telegram_id, "text": MESSAGE, "parse_mode": "Markdown"},
            timeout=10
        )
        return (telegram_id, r.status_code, r.text if r.status_code != 200 else "OK")
    except Exception as e:
        return (telegram_id, 0, str(e))

# Load user IDs
print("Loading users...")
with app.app_context():
    user_ids = [u.telegram_id for u in User.query.all()]

print(f"Sending to {len(user_ids)} users with 20 parallel threads...")

success, blocked, failed = 0, 0, 0

# Send in parallel
with ThreadPoolExecutor(max_workers=20) as executor:
    futures = {executor.submit(send_message, uid): uid for uid in user_ids}
    
    for i, future in enumerate(as_completed(futures), 1):
        uid, code, msg = future.result()
        
        if code == 200:
            success += 1
        elif code == 403:
            blocked += 1
        else:
            failed += 1
            if failed <= 10:  # Show first 10 errors only
                print(f"Error {uid}: {msg[:80]}")
        
        if i % 100 == 0:
            print(f"Progress: {i}/{len(user_ids)} - ✅ {success} | 🚫 {blocked} | ❌ {failed}")

print(f"\n✅ Sent: {success} | 🚫 Blocked: {blocked} | ❌ Failed: {failed}")
print(f"Success rate: {success/(len(user_ids)-blocked)*100:.1f}%")
