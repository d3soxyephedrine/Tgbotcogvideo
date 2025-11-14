import os
from main import app, db
from models import User
import requests
import time

BOT_TOKEN = os.environ.get("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

discord_announcement = """
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

BATCH_SIZE = 50
DELAY_BETWEEN_MESSAGES = 0.05  # 50ms between messages
DELAY_BETWEEN_BATCHES = 2  # 2 seconds between batches

def send_discord_announcement():
    # Step 1: Load all user IDs and close DB connection immediately
    print("📊 Loading user IDs from database...")
    with app.app_context():
        user_ids = [user.telegram_id for user in User.query.all()]
    
    total_users = len(user_ids)
    print(f"✅ Loaded {total_users} user IDs")
    print(f"📦 Batch size: {BATCH_SIZE}")
    print(f"⏱️ Delay between messages: {DELAY_BETWEEN_MESSAGES}s")
    print(f"⏱️ Delay between batches: {DELAY_BETWEEN_BATCHES}s")
    print()
    
    success = 0
    failed = 0
    blocked = 0
    
    # Step 2: Send messages in batches (no DB connection needed)
    for batch_num in range(0, total_users, BATCH_SIZE):
        batch = user_ids[batch_num:batch_num + BATCH_SIZE]
        batch_index = batch_num // BATCH_SIZE + 1
        total_batches = (total_users + BATCH_SIZE - 1) // BATCH_SIZE
        
        print(f"📦 Processing batch {batch_index}/{total_batches} ({len(batch)} users)...")
        
        for telegram_id in batch:
            try:
                response = requests.post(
                    f"{BASE_URL}/sendMessage",
                    json={
                        "chat_id": telegram_id,
                        "text": discord_announcement,
                        "parse_mode": "Markdown"
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    success += 1
                elif response.status_code == 403:
                    blocked += 1
                else:
                    failed += 1
                    print(f"  ⚠️ Failed: {telegram_id} - {response.text[:100]}")
                
                time.sleep(DELAY_BETWEEN_MESSAGES)
                
            except Exception as e:
                failed += 1
                print(f"  ❌ Error: {telegram_id} - {str(e)[:100]}")
        
        # Progress update after each batch
        print(f"  ✅ Batch {batch_index} complete: {success} sent, {blocked} blocked, {failed} errors")
        
        # Delay between batches (except for the last batch)
        if batch_num + BATCH_SIZE < total_users:
            time.sleep(DELAY_BETWEEN_BATCHES)
    
    print()
    print("=" * 60)
    print(f"📊 FINAL RESULTS:")
    print(f"  ✅ Successfully sent: {success}")
    print(f"  🚫 Blocked users: {blocked}")
    print(f"  ❌ Failed: {failed}")
    print(f"  📈 Success rate: {(success / (total_users - blocked) * 100):.1f}%")
    print("=" * 60)

if __name__ == "__main__":
    send_discord_announcement()
