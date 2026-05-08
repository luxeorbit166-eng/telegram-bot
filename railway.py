"""
Railway Webhook Server for Video Editor Bot v39 ULTRA
=====================================================
This module provides webhook support for Railway deployment.
Railway uses webhooks instead of long-polling, so we need to:
1. Set up a webhook endpoint
2. Handle graceful shutdown

Usage:
    Railway will automatically run this file via the Start Command
    Configure in Railway: Start Command = python railway.py
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

# Add parent directory to path so we can import the bot
sys.path.insert(0, str(Path(__file__).parent))

# Import the main bot module
from user_input_files import video_editor_bot_v39_ULTRA as bot_module

# Railway provides PORT environment variable
PORT = int(os.getenv("PORT", 8080))
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
RAILWAY_DEPLOYMENT_ID = os.getenv("RAILWAY_DEPLOYMENT_ID", "")

logger = logging.getLogger(__name__)


async def set_webhook(app, bot_token: str):
    """Set webhook URL with Telegram."""
    if not RAILWAY_PUBLIC_DOMAIN:
        logger.warning("RAILWAY_PUBLIC_DOMAIN not set, cannot set webhook")
        return False

    # Construct webhook URL
    webhook_url = f"https://{RAILWAY_PUBLIC_DOMAIN}/webhook/{bot_token}"

    try:
        await app.bot.delete_webhook()
        await app.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to: {webhook_url}")
        return True
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")
        return False


async def run_webhook_server(app):
    """Run the webhook server using aiohttp."""
    from aiohttp import web

    # Ensure webhook is set
    await set_webhook(app, bot_module.BOT_TOKEN)

    async def handle_webhook(request):
        """Handle incoming Telegram webhook requests."""
        try:
            data = await request.json()
            update = bot_module.Update.de_json(data, app.bot)
            await app.process_update(update)
            return web.Response(text="OK")
        except Exception as e:
            logger.error(f"Error processing update: {e}")
            return web.Response(text="Error", status=500)

    async def handle_health(request):
        """Health check endpoint for Railway."""
        return web.Response(text="OK", content_type="text/plain")

    app_aiohttp = web.Application()
    app_aiohttp.router.add_post(f"/webhook/{bot_module.BOT_TOKEN}", handle_webhook)
    app_aiohttp.router.add_get("/health", handle_health)

    runner = web.AppRunner(app_aiohttp)
    await runner.setup()
    site = web.TCSite(runner, "0.0.0.0", PORT)
    await site.start()

    logger.info(f"Webhook server running on port {PORT}")

    # Keep server running
    while True:
        await asyncio.sleep(3600)


async def main():
    """Main entry point for Railway deployment."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    print(f"""
╔═══════════════════════════════════════════════════╗
║  🚂 Railway Webhook Server                       ║
║  🎬 Video Editor Bot v39 ULTRA                  ║
║  🌐 Webhook Mode ( Railway optimized )           ║
╚═══════════════════════════════════════════════════╝
    """)

    # Initialize the bot application
    app = (bot_module.Application.builder()
           .token(bot_module.BOT_TOKEN)
           .connect_timeout(45.0)
           .read_timeout(90.0)
           .write_timeout(180.0)
           .pool_timeout(60.0)
           .get_updates_connect_timeout(45.0)
           .get_updates_read_timeout(90.0)
           .get_updates_pool_timeout(60.0)
           .build())

    # Register all handlers from the original bot
    bot_module.register_handlers(app)

    # Start webhook server instead of polling
    try:
        await run_webhook_server(app)
    except KeyboardInterrupt:
        print("\n👋 Shutting down gracefully...")
    finally:
        print("✅ Server stopped")


if __name__ == "__main__":
    # On Railway, run the webhook server
    asyncio.run(main())
