#!/bin/bash
# ==============================================================================
# 24/7 Service Manager for AutoShop Discord Bot (macOS launchd)
# ==============================================================================

PROJECT_DIR="/Users/vivekdalmia/.gemini/antigravity/scratch/autoshop-discord-bot"
PLIST_NAME="com.autoshop.discordbot.plist"
PLIST_SOURCE="$PROJECT_DIR/$PLIST_NAME"
PLIST_TARGET="$HOME/Library/LaunchAgents/$PLIST_NAME"

mkdir -p "$HOME/Library/LaunchAgents"

case "$1" in
  start|install)
    echo "📦 Installing and starting 24/7 background service..."
    cp "$PLIST_SOURCE" "$PLIST_TARGET"
    launchctl unload "$PLIST_TARGET" 2>/dev/null
    launchctl load -w "$PLIST_TARGET"
    echo "✅ Bot service installed and running in the background!"
    echo "• Auto-starts on login/boot: YES"
    echo "• Auto-restarts if crashed: YES"
    echo "• View live logs: ./service_manager.sh logs"
    ;;

  stop|uninstall)
    echo "🛑 Stopping background service..."
    launchctl unload -w "$PLIST_TARGET" 2>/dev/null
    rm -f "$PLIST_TARGET"
    echo "✅ Bot service stopped."
    ;;

  status)
    echo "🔍 Checking service status..."
    if launchctl list | grep -q "com.autoshop.discordbot"; then
      echo "🟢 Service is active and running!"
      launchctl list | grep "com.autoshop.discordbot"
    else
      echo "🔴 Service is not running."
    fi
    ;;

  logs)
    echo "📜 Streaming bot live logs (Press Ctrl+C to exit)..."
    touch "$PROJECT_DIR/bot.log"
    tail -f "$PROJECT_DIR/bot.log"
    ;;

  restart)
    echo "🔄 Restarting service..."
    launchctl unload "$PLIST_TARGET" 2>/dev/null
    launchctl load -w "$PLIST_TARGET"
    echo "✅ Service restarted."
    ;;

  *)
    echo "Usage: ./service_manager.sh {start|stop|restart|status|logs}"
    exit 1
    ;;
esac
