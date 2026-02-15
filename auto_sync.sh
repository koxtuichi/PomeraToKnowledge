#!/bin/bash

# Configuration
PROJECT_DIR="/Users/sugimotokoichi/Documents/ポメラtoナレッジグラフ"
LOG_FILE="$PROJECT_DIR/auto_sync.log"

# Load configuration from .env
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
else
    echo "Error: .env file not found at $PROJECT_DIR/.env" >> "$LOG_FILE"
    exit 1
fi

# Navigate to project directory
cd "$PROJECT_DIR"

# Run sync script
echo "[$(date)] Starting Auto Sync..." >> "$LOG_FILE"
/usr/bin/python3 sync_email.py >> "$LOG_FILE" 2>&1
echo "[$(date)] Sync Finished." >> "$LOG_FILE"
