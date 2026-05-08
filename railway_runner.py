"""
Railway Deployment Wrapper for Video Editor Bot v39 ULTRA
=========================================================
This module serves as the entry point for Railway deployment.
Railway supports long-running processes, so we can use polling mode
with the built-in watchdog.

Railway Configuration:
---------------------
1. Set the following environment variables in Railway:
   - BOT_TOKEN: Your Telegram bot token
   - ADMIN_ID: Your Telegram user ID
   - Any optional API keys (GEMINI_API_KEY, etc.)

2. Start Command: python railway_runner.py

3. The bot will run with automatic reconnection and watchdog features.
"""

import os
import sys
import signal
from pathlib import Path

# Add workspace to path
sys.path.insert(0, "/workspace")

# Import the original bot module
import user_input_files.video_editor_bot_v39_ULTRA as bot

# Railway provides these environment variables
RAILWAY_STATIC_URL = os.getenv("RAILWAY_STATIC_URL", "")
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")


def graceful_shutdown(signum, frame):
    """Handle graceful shutdown on Railway."""
    print("\n🚂 Railway shutdown signal received...")
    print("✅ Bot will restart automatically if needed.")
    sys.exit(0)


def run_railway():
    """Run the bot with Railway-optimized settings."""
    print(f"""
╔═══════════════════════════════════════════════════╗
║  🚂 Railway Deployment                           ║
║  🎬 Video Editor Bot v39 ULTRA                  ║
║  📡 Polling Mode (with auto-reconnect)          ║
╚═══════════════════════════════════════════════════╝
    """)

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    # Print deployment info
    if RAILWAY_PUBLIC_DOMAIN:
        print(f"📍 Deployment Domain: {RAILWAY_PUBLIC_DOMAIN}")

    # Ensure Bengali fonts are available
    try:
        bot.ensure_bangla_fonts()
    except Exception as e:
        bot.logger.warning("Bengali font setup failed: %s", e)

    # Initial cleanup
    bot.cleanup_temp()

    # Run in direct mode (no watchdog, Railway handles restarts)
    sys.argv = [sys.argv[0], "--direct"]
    bot.main()


if __name__ == "__main__":
    run_railway()
