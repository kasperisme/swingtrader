#!/bin/bash
export OPENCLAW_CMD=/Users/kasperisme/.openclaw/tmp/agent-cli/openclaw
export OPENCLAW_WHATSAPP_TO=+4528256265
cd /Users/kasperisme/projects/swingtrader/code/analytics
.venv/bin/python3 -m scripts.watchdog >> /Users/kasperisme/projects/swingtrader/logs/watchdog.log 2>&1
