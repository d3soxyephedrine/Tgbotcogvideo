#!/usr/bin/env python3
"""
Script to unlock video generation for users by setting last_purchase_at timestamp.
This bypasses the video generation paywall for testing purposes.
"""

from models import db, User
from main import app
from datetime import datetime

def unlock_video_for_all_users():
    """Unlock video generation for all users in the database"""
    with app.app_context():
        users = User.query.all()

        if not users:
            print("No users found in database.")
            return

        print(f"Found {len(users)} user(s)\n")

        for user in users:
            print(f"User: {user.username or 'Unknown'} (Telegram ID: {user.telegram_id})")
            print(f"  Credits: {user.credits}")
            print(f"  Daily Credits: {user.daily_credits}")
            print(f"  Last Purchase: {user.last_purchase_at}")

            if not user.last_purchase_at:
                user.last_purchase_at = datetime.utcnow()
                db.session.commit()
                print(f"  ✅ UNLOCKED - Set last_purchase_at to {user.last_purchase_at}")
            else:
                print(f"  ✓ Already unlocked")

            print()

def unlock_video_for_user(telegram_id: int):
    """Unlock video generation for a specific user"""
    with app.app_context():
        user = User.query.filter_by(telegram_id=telegram_id).first()

        if not user:
            print(f"❌ User with Telegram ID {telegram_id} not found.")
            return

        print(f"User: {user.username or 'Unknown'} (Telegram ID: {user.telegram_id})")
        print(f"  Credits: {user.credits}")
        print(f"  Daily Credits: {user.daily_credits}")
        print(f"  Last Purchase: {user.last_purchase_at}")

        if not user.last_purchase_at:
            user.last_purchase_at = datetime.utcnow()
            db.session.commit()
            print(f"  ✅ UNLOCKED - Set last_purchase_at to {user.last_purchase_at}")
        else:
            print(f"  ✓ Already unlocked")

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Unlock specific user by Telegram ID
        try:
            telegram_id = int(sys.argv[1])
            unlock_video_for_user(telegram_id)
        except ValueError:
            print("❌ Invalid Telegram ID. Please provide a numeric ID.")
            print("Usage: python unlock_video.py [telegram_id]")
    else:
        # Unlock all users
        unlock_video_for_all_users()
