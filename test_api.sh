#!/bin/bash

# Usage information
show_help() {
    echo "Test the Telegram Bot API and LLM integrations"
    echo ""
    echo "Usage: ./test_api.sh [option] [message]"
    echo "Options:"
    echo "  -h, --help     Show this help"
    echo "  -b, --bot      Test the bot response (default)"
    echo "  -m, --models   Test both models side by side"
    echo "  -s, --stats    Show usage statistics"
    echo ""
    echo "Example:"
    echo "  ./test_api.sh \"Tell me a joke\""
    echo "  ./test_api.sh -m \"What is the meaning of life?\""
}

# Base URL
BASE_URL="http://localhost:5000"

# Default test mode
TEST_MODE="bot"

# Parse arguments
case "$1" in
    -h|--help)
        show_help
        exit 0
        ;;
    -m|--models)
        TEST_MODE="models"
        shift
        ;;
    -s|--stats)
        TEST_MODE="stats"
        shift
        ;;
    -b|--bot)
        TEST_MODE="bot"
        shift
        ;;
esac

# Get the message
if [ -z "$1" ] && [ "$TEST_MODE" != "stats" ]; then
    echo "Error: Message is required"
    show_help
    exit 1
fi

MESSAGE="$1"

# Perform the test
case "$TEST_MODE" in
    bot)
        echo "Testing bot with message: $MESSAGE"
        curl -s -X POST "$BASE_URL/test" \
            -H "Content-Type: application/json" \
            -d "{\"message\": \"$MESSAGE\"}" | jq
        ;;
    models)
        echo "Testing both models with message: $MESSAGE"
        curl -s -X POST "$BASE_URL/test_models" \
            -H "Content-Type: application/json" \
            -d "{\"message\": \"$MESSAGE\"}" | jq
        ;;
    stats)
        echo "Fetching usage statistics"
        curl -s "$BASE_URL/stats" | jq
        ;;
esac