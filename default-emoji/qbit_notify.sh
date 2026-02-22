#!/bin/bash

source "./.env"
TORRENT_NAME="$1"

# Send Notification
curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
     -d chat_id="$ADMIN_ID" \
     -d parse_mode="HTML" \
     --data-urlencode text="<b>✅ Download Complete:</b> $TORRENT_NAME"