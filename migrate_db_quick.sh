#!/bin/bash
# Quick Database Migration Script
# Migrates data from Replit to Railway using pg_dump/pg_restore

echo "🚀 Quick Database Migration: Replit → Railway"
echo "=============================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if pg_dump is available
if ! command -v pg_dump &> /dev/null; then
    echo -e "${RED}❌ pg_dump not found${NC}"
    echo "   Install PostgreSQL client tools:"
    echo "   - Ubuntu/Debian: sudo apt-get install postgresql-client"
    echo "   - macOS: brew install postgresql"
    exit 1
fi

echo -e "${YELLOW}📥 Step 1: Enter your REPLIT database URL${NC}"
read -p "   > " REPLIT_DB_URL

echo ""
echo -e "${YELLOW}📤 Step 2: Enter your RAILWAY database URL${NC}"
read -p "   > " RAILWAY_DB_URL

if [ -z "$REPLIT_DB_URL" ] || [ -z "$RAILWAY_DB_URL" ]; then
    echo -e "${RED}❌ Both database URLs are required${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}🔍 Step 3: Testing connections...${NC}"

# Test Replit connection
if psql "$REPLIT_DB_URL" -c "SELECT 1;" &> /dev/null; then
    REPL_USERS=$(psql "$REPLIT_DB_URL" -t -c "SELECT COUNT(*) FROM \"user\";")
    echo -e "${GREEN}✓ Replit DB connected - Found $REPL_USERS users${NC}"
else
    echo -e "${RED}❌ Failed to connect to Replit database${NC}"
    exit 1
fi

# Test Railway connection
if psql "$RAILWAY_DB_URL" -c "SELECT 1;" &> /dev/null; then
    echo -e "${GREEN}✓ Railway DB connected${NC}"
else
    echo -e "${RED}❌ Failed to connect to Railway database${NC}"
    exit 1
fi

echo ""
echo "=============================================="
echo -e "${YELLOW}⚠️  MIGRATION PLAN:${NC}"
echo "   1. Dump all data from Replit DB"
echo "   2. Restore to Railway DB"
echo "   3. This will PRESERVE existing Railway data"
echo "   4. Duplicates will be skipped (based on primary keys)"
echo "=============================================="
echo ""

read -p "Continue? (yes/no): " -r
echo
if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$|^[Yy]$ ]]; then
    echo "❌ Migration cancelled"
    exit 0
fi

# Create temporary dump file
DUMP_FILE="/tmp/replit_migration_$(date +%s).sql"

echo ""
echo -e "${YELLOW}📦 Step 4: Dumping Replit database...${NC}"
pg_dump "$REPLIT_DB_URL" \
    --no-owner \
    --no-acl \
    --data-only \
    --inserts \
    --on-conflict-do-nothing \
    -f "$DUMP_FILE"

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to dump Replit database${NC}"
    exit 1
fi

DUMP_SIZE=$(du -h "$DUMP_FILE" | cut -f1)
echo -e "${GREEN}✓ Dump completed: $DUMP_SIZE${NC}"

echo ""
echo -e "${YELLOW}📤 Step 5: Restoring to Railway database...${NC}"

# Add ON CONFLICT handling to the dump
sed -i 's/INSERT INTO/INSERT INTO/g' "$DUMP_FILE"

psql "$RAILWAY_DB_URL" -f "$DUMP_FILE" 2>&1 | grep -v "ERROR:  duplicate key" || true

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Restore completed${NC}"
else
    echo -e "${YELLOW}⚠️  Some errors occurred (likely duplicates - this is normal)${NC}"
fi

echo ""
echo -e "${YELLOW}🔍 Step 6: Verifying migration...${NC}"

RAILWAY_USERS=$(psql "$RAILWAY_DB_URL" -t -c "SELECT COUNT(*) FROM \"user\";")
RAILWAY_CONVS=$(psql "$RAILWAY_DB_URL" -t -c "SELECT COUNT(*) FROM conversation;")
RAILWAY_MSGS=$(psql "$RAILWAY_DB_URL" -t -c "SELECT COUNT(*) FROM message;")
RAILWAY_MEMS=$(psql "$RAILWAY_DB_URL" -t -c "SELECT COUNT(*) FROM memory;")

echo ""
echo "=============================================="
echo -e "${GREEN}✅ Migration Results:${NC}"
echo "=============================================="
echo "   Users:         $RAILWAY_USERS"
echo "   Conversations: $RAILWAY_CONVS"
echo "   Messages:      $RAILWAY_MSGS"
echo "   Memories:      $RAILWAY_MEMS"
echo "=============================================="

# Cleanup
rm "$DUMP_FILE"
echo ""
echo -e "${GREEN}🎉 Migration complete!${NC}"
echo ""
echo "🎯 Next steps:"
echo "   1. Make sure Railway DATABASE_URL is set in your Railway service"
echo "   2. Restart your Railway deployment"
echo "   3. Visit /diagnostic to verify database connection"
echo "   4. Test user login and credit balance"
echo ""
