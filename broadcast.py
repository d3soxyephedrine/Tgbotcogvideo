#!/usr/bin/env python3
"""
Broadcast script to send notifications to all users
"""
import os
import sys
import time
from models import db, User
from telegram_handler import send_message
from main import app

def broadcast_message(message_text):
    """Send a message to all users in the database
    
    Args:
        message_text (str): The message to broadcast
    
    Returns:
        dict: Statistics about the broadcast (sent, failed, total)
    """
    stats = {
        'total': 0,
        'sent': 0,
        'failed': 0,
        'errors': []
    }
    
    with app.app_context():
        # Get all users
        users = User.query.all()
        stats['total'] = len(users)
        
        print(f"Starting broadcast to {stats['total']} users...")
        
        for user in users:
            try:
                # Send message
                result = send_message(user.telegram_id, message_text)
                
                # Check if successful
                if result.get('ok'):
                    stats['sent'] += 1
                    print(f"✓ Sent to {user.username or user.telegram_id}")
                else:
                    stats['failed'] += 1
                    error_msg = result.get('description', 'Unknown error')
                    stats['errors'].append(f"{user.telegram_id}: {error_msg}")
                    print(f"✗ Failed to send to {user.username or user.telegram_id}: {error_msg}")
                
                # Rate limiting - Telegram allows ~30 messages per second
                time.sleep(0.05)
                
            except Exception as e:
                stats['failed'] += 1
                stats['errors'].append(f"{user.telegram_id}: {str(e)}")
                print(f"✗ Error sending to {user.username or user.telegram_id}: {str(e)}")
    
    return stats

if __name__ == "__main__":
    # Message to broadcast
    message = """🎉 Great News! The Bot is Back Online! 🎉

Your AI assistant is now fully operational and ready to help you with:

✨ Smart conversations with ChatGPT-4o
🎨 Image generation with Grok-2
📝 Professional writing mode (/write)
💬 Full conversation history

🎁 BONUS: Users with zero credits just received 30 free credits!

Try these commands:
/help - See all available features
/balance - Check your credit balance
/write - Activate professional writing mode
/imagine - Generate AI images

Let's chat! 🚀"""

    print("=" * 60)
    print("BROADCAST NOTIFICATION")
    print("=" * 60)
    print(f"\nMessage:\n{message}\n")
    print("=" * 60)
    
    # Send broadcast
    stats = broadcast_message(message)
    
    # Print summary
    print("\n" + "=" * 60)
    print("BROADCAST COMPLETE")
    print("=" * 60)
    print(f"Total users: {stats['total']}")
    print(f"Successfully sent: {stats['sent']}")
    print(f"Failed: {stats['failed']}")
    
    if stats['errors']:
        print(f"\nErrors:")
        for error in stats['errors'][:10]:  # Show first 10 errors
            print(f"  - {error}")
        if len(stats['errors']) > 10:
            print(f"  ... and {len(stats['errors']) - 10} more errors")
    
    print("=" * 60)
