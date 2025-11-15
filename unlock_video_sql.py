#!/usr/bin/env python3
"""
Script to unlock video generation using direct SQL queries.
Sets last_purchase_at for all users to bypass video paywall.
"""

import os
import sqlite3
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bot.db")

# Extract SQLite path from DATABASE_URL
if DATABASE_URL.startswith("sqlite:///"):
    db_path = DATABASE_URL.replace("sqlite:///", "")
else:
    print(f"❌ This script only works with SQLite databases.")
    print(f"   Current DATABASE_URL: {DATABASE_URL}")
    exit(1)

print(f"Using database: {db_path}\n")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get all users
    cursor.execute("SELECT id, telegram_id, username, credits, daily_credits, last_purchase_at FROM user")
    users = cursor.fetchall()

    if not users:
        print("No users found in database.")
        conn.close()
        exit(0)

    print(f"Found {len(users)} user(s)\n")

    now = datetime.utcnow().isoformat()

    for user in users:
        user_id, telegram_id, username, credits, daily_credits, last_purchase_at = user

        print(f"User: {username or 'Unknown'} (Telegram ID: {telegram_id})")
        print(f"  Credits: {credits}")
        print(f"  Daily Credits: {daily_credits}")
        print(f"  Last Purchase: {last_purchase_at or 'None'}")

        if not last_purchase_at:
            cursor.execute(
                "UPDATE user SET last_purchase_at = ? WHERE id = ?",
                (now, user_id)
            )
            conn.commit()
            print(f"  ✅ UNLOCKED - Set last_purchase_at to {now}")
        else:
            print(f"  ✓ Already unlocked")

        print()

    conn.close()
    print("✅ Done!")

except sqlite3.Error as e:
    print(f"❌ Database error: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
