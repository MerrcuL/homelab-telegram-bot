#!/bin/bash
# Universal Telegram Push Script using .env

# 1. Define the absolute path to your .env file
ENV_FILE="/home/anton/server-bot/.env"

# 2. Check if file exists and load variables
if [ -f "$ENV_FILE" ]; then
    # Source the file to load BOT_TOKEN and ADMIN_ID into this script
    source "$ENV_FILE"
else
    echo "Error: .env file not found at $ENV_FILE"
    exit 1
fi

MESSAGE=$1

# 3. Execute the curl command using the loaded variables
curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d chat_id="${ADMIN_ID}" \
    -d text="<b>⚠️SYSTEM ALERT</b>%0A${MESSAGE}" \
    -d parse_mode="HTML" > /dev/null