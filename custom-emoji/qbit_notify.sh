#!/bin/bash

source "./.env"
TORRENT_NAME="$1"

# Send Notification
curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
     -d chat_id="$ADMIN_ID" \
     -d parse_mode="HTML" \
     --data-urlencode text="<tg-emoji emoji-id=\"5427009714745517609\">✅</tg-emoji> <b>Download Complete:</b> $TORRENT_NAME"