import os
import sys
from main import app, db
from models import User
import requests
import time

BOT_TOKEN = os.environ.get("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

announcement = """
🎉 *KO2 Bot Update - All Systems Operational!*

I'm happy to announce that all bot features are now fully functional and working properly! 

✅ *What's working:*
• Chat with AI (DeepSeek & GPT-4o models)
• Image generation (/imagine, /grok, /uncensored, /edit)
• Video generation (/vid - image-to-video)
• Credit system & payments
• Web chat interface
• All core commands

🔧 *Recent improvements:*
• Fixed video delivery system
• Enhanced API reliability
• Improved error handling
• Better timeout management

💡 *Coming soon:*
New video generation features will be announced shortly!

Thank you for your patience and continued support! 🙏
"""

BATCH_SIZE = 50
DELAY_BETWEEN_MESSAGES = 0.05  # 50ms between messages
DELAY_BETWEEN_BATCHES = 2  # 2 seconds between batches

def send_announcement():
    with app.app_context():
        users = User.query.all()
        total_users = len(users)
        print(f"📊 Total users: {total_users}")
        print(f"📦 Batch size: {BATCH_SIZE}")
        print(f"⏱️ Delay between messages: {DELAY_BETWEEN_MESSAGES}s")
        print(f"⏱️ Delay between batches: {DELAY_BETWEEN_BATCHES}s")
        print()
        
        success = 0
        failed = 0
        blocked = 0
        
        # Process in batches
        for batch_num in range(0, total_users, BATCH_SIZE):
            batch = users[batch_num:batch_num + BATCH_SIZE]
            batch_index = batch_num // BATCH_SIZE + 1
            total_batches = (total_users + BATCH_SIZE - 1) // BATCH_SIZE
            
            print(f"📦 Processing batch {batch_index}/{total_batches} ({len(batch)} users)...")
            
            for user in batch:
                try:
                    response = requests.post(
                        f"{BASE_URL}/sendMessage",
                        json={
                            "chat_id": user.telegram_id,
                            "text": announcement,
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
                        print(f"  ⚠️ Failed: {user.telegram_id} - {response.text[:100]}")
                    
                    time.sleep(DELAY_BETWEEN_MESSAGES)
                    
                except Exception as e:
                    failed += 1
                    print(f"  ❌ Error: {user.telegram_id} - {str(e)[:100]}")
            
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
        print(f"  📈 Success rate: {(success / total_users * 100):.1f}%")
        print("=" * 60)

if __name__ == "__main__":
    send_announcement()
