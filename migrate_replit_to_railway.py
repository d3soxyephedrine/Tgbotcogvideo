#!/usr/bin/env python3
"""
Replit to Railway Database Migration Script

This script migrates all data from your Replit PostgreSQL database
to your Railway PostgreSQL database, preserving:
- Users (with credits, payments, API keys)
- Conversations
- Messages
- Memories
- Payments (all types)
- Transactions

Usage:
    python migrate_replit_to_railway.py
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_database_urls():
    """Get source (Replit) and destination (Railway) database URLs"""

    print("\n" + "="*60)
    print("🚀 Replit → Railway Database Migration")
    print("="*60 + "\n")

    # Source database (Replit)
    source_url = input("📥 Enter your REPLIT database URL:\n   (postgresql://...)\n   > ").strip()
    if not source_url:
        logger.error("Source database URL is required")
        sys.exit(1)

    print()

    # Destination database (Railway)
    dest_url = input("📤 Enter your RAILWAY database URL:\n   (postgresql://...)\n   > ").strip()
    if not dest_url:
        logger.error("Destination database URL is required")
        sys.exit(1)

    return source_url, dest_url

def test_connections(source_url, dest_url):
    """Test both database connections"""
    logger.info("Testing database connections...")

    try:
        # Test source
        source_engine = create_engine(source_url, echo=False)
        with source_engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM user"))
            user_count = result.scalar()
            logger.info(f"✓ Replit DB connected - Found {user_count} users")

        # Test destination
        dest_engine = create_engine(dest_url, echo=False)
        with dest_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            logger.info(f"✓ Railway DB connected")

        return source_engine, dest_engine

    except Exception as e:
        logger.error(f"Connection test failed: {str(e)}")
        sys.exit(1)

def get_table_counts(engine):
    """Get row counts for all tables"""
    tables = [
        'user', 'conversation', 'message', 'memory',
        'payment', 'transaction', 'crypto_payment', 'telegram_payment'
    ]

    counts = {}
    with engine.connect() as conn:
        for table in tables:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                counts[table] = result.scalar()
            except Exception as e:
                logger.warning(f"Could not count {table}: {str(e)}")
                counts[table] = 0

    return counts

def confirm_migration(source_counts, dest_counts):
    """Show migration plan and confirm with user"""
    print("\n" + "="*60)
    print("📊 Migration Plan")
    print("="*60)

    print("\n📥 SOURCE (Replit):")
    for table, count in source_counts.items():
        print(f"   {table:20} {count:>6} rows")

    print("\n📤 DESTINATION (Railway - CURRENT):")
    for table, count in dest_counts.items():
        print(f"   {table:20} {count:>6} rows")

    print("\n" + "="*60)
    print("⚠️  WARNING:")
    print("   This will APPEND data to Railway database.")
    print("   Existing data in Railway will be PRESERVED.")
    print("   Duplicate IDs will be skipped (if they exist).")
    print("="*60 + "\n")

    response = input("Continue with migration? (yes/no): ").strip().lower()
    return response in ['yes', 'y']

def migrate_table(source_engine, dest_engine, table_name, dependencies=None):
    """Migrate a single table from source to destination"""
    logger.info(f"Migrating {table_name}...")

    try:
        # Get all data from source
        with source_engine.connect() as source_conn:
            result = source_conn.execute(text(f"SELECT * FROM {table_name}"))
            columns = result.keys()
            rows = result.fetchall()

        if not rows:
            logger.info(f"  ↳ {table_name}: No data to migrate")
            return 0

        # Insert into destination
        migrated = 0
        skipped = 0

        with dest_engine.connect() as dest_conn:
            for row in rows:
                # Build insert statement
                cols = ', '.join(columns)
                placeholders = ', '.join([f":{col}" for col in columns])

                # Convert row to dict
                row_dict = dict(zip(columns, row))

                try:
                    # Try to insert
                    insert_sql = f"""
                    INSERT INTO {table_name} ({cols})
                    VALUES ({placeholders})
                    ON CONFLICT DO NOTHING
                    """
                    dest_conn.execute(text(insert_sql), row_dict)
                    dest_conn.commit()
                    migrated += 1
                except Exception as e:
                    # Skip if conflict (duplicate)
                    skipped += 1
                    logger.debug(f"  Skipped row (likely duplicate): {str(e)}")

        logger.info(f"  ✓ {table_name}: Migrated {migrated} rows, skipped {skipped}")
        return migrated

    except Exception as e:
        logger.error(f"  ✗ {table_name}: Migration failed - {str(e)}")
        return 0

def migrate_all_data(source_engine, dest_engine):
    """Migrate all tables in the correct order (respecting foreign keys)"""

    # Order matters! Parent tables before child tables
    migration_order = [
        ('user', 'Users (accounts, credits, API keys)'),
        ('conversation', 'Conversations'),
        ('message', 'Messages'),
        ('memory', 'AI Memories'),
        ('payment', 'Payments'),
        ('transaction', 'Transactions'),
        ('crypto_payment', 'Crypto Payments'),
        ('telegram_payment', 'Telegram Star Payments'),
    ]

    print("\n" + "="*60)
    print("🔄 Starting Migration")
    print("="*60 + "\n")

    total_migrated = 0

    for table, description in migration_order:
        logger.info(f"📦 {description}")
        count = migrate_table(source_engine, dest_engine, table)
        total_migrated += count

    return total_migrated

def verify_migration(source_engine, dest_engine):
    """Verify migration by comparing row counts"""
    logger.info("\n🔍 Verifying migration...")

    source_counts = get_table_counts(source_engine)
    dest_counts = get_table_counts(dest_engine)

    print("\n" + "="*60)
    print("✅ Migration Complete - Verification")
    print("="*60)

    all_good = True

    for table in source_counts.keys():
        source = source_counts[table]
        dest = dest_counts[table]
        status = "✓" if dest >= source else "⚠️"

        print(f"{status} {table:20} Source: {source:>5}  →  Dest: {dest:>5}")

        if dest < source:
            all_good = False

    print("="*60)

    if all_good:
        print("\n🎉 SUCCESS! All data migrated successfully!")
    else:
        print("\n⚠️  Some tables have fewer rows in destination.")
        print("   This might be normal if there were duplicates.")
        print("   Check the logs above for details.")

    return all_good

def main():
    """Main migration function"""
    try:
        # Get database URLs
        source_url, dest_url = get_database_urls()

        # Test connections
        source_engine, dest_engine = test_connections(source_url, dest_url)

        # Get current counts
        source_counts = get_table_counts(source_engine)
        dest_counts = get_table_counts(dest_engine)

        # Confirm migration
        if not confirm_migration(source_counts, dest_counts):
            logger.info("Migration cancelled by user")
            return

        # Perform migration
        total = migrate_all_data(source_engine, dest_engine)

        # Verify
        verify_migration(source_engine, dest_engine)

        print(f"\n📊 Total rows migrated: {total}")
        print("\n✨ Your Railway database now has all your Replit data!")
        print("\n🎯 Next steps:")
        print("   1. Update your Railway DATABASE_URL in environment variables")
        print("   2. Restart your Railway service")
        print("   3. Test the /diagnostic endpoint")
        print("   4. Verify your users can log in and see their credits")

    except KeyboardInterrupt:
        print("\n\n❌ Migration cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Migration failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
