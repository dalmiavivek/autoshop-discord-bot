import os
import sys
import logging
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import OrderDatabase
from providers import get_store_provider

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("AutoShopBot")

# Load environment configuration
load_dotenv()

class AutoShopBot(commands.Bot):
    def __init__(self):
        # Use standard default intents (Slash commands and role assignment do not require privileged intents)
        intents = discord.Intents.default()

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

        self.db = OrderDatabase("orders.db")
        self.provider = get_store_provider()

        if not self.provider:
            logger.warning("No store provider configured! Check your STORE_PLATFORM in .env.")

    async def setup_hook(self):
        """Asynchronous setup hook to load cogs and sync slash commands."""
        # Load cogs
        initial_extensions = [
            "cogs.stock_admin",
            "cogs.customer_shop"
        ]

        for ext in initial_extensions:
            try:
                await self.load_extension(ext)
                logger.info(f"Loaded extension: {ext}")
            except Exception as e:
                logger.error(f"Failed to load extension {ext}: {e}", exc_info=True)

        # Automatic slash command synchronization
        guild_id = os.getenv("GUILD_ID", "").strip()
        if guild_id.isdigit():
            try:
                guild = discord.Object(id=int(guild_id))
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logger.info(f"Synced {len(synced)} slash commands to guild {guild_id} (Instant dev mode)")
            except discord.Forbidden:
                logger.warning(
                    f"Could not sync commands to Guild {guild_id}: 403 Missing Access. "
                    "The bot is either not invited to that server yet, or needs the 'applications.commands' scope. "
                    "Bot will continue running and sync globally."
                )
                try:
                    synced = await self.tree.sync()
                    logger.info(f"Synced {len(synced)} global slash commands instead.")
                except Exception as e:
                    logger.warning(f"Global sync also failed: {e}")
            except Exception as e:
                logger.warning(f"Failed to sync commands to guild {guild_id}: {e}")
        else:
            try:
                synced = await self.tree.sync()
                logger.info(f"Synced {len(synced)} global slash commands")
            except Exception as e:
                logger.warning(f"Global sync failed: {e}")

    async def on_ready(self):
        platform_name = os.getenv("STORE_PLATFORM", "shoppex").upper()
        logger.info("=" * 45)
        logger.info(f"Logged in as: {self.user} (ID: {self.user.id})")
        logger.info(f"Connected Store Platform: {platform_name}")
        logger.info(f"Guilds connected: {len(self.guilds)}")
        logger.info("=" * 45)

        # Set rich presence
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="/shop | Live Stock Sync"
        )
        await self.change_presence(status=discord.Status.online, activity=activity)


async def main():
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "your_discord_bot_token_here":
        logger.error("DISCORD_TOKEN is missing or not set in .env file!")
        logger.error("Please edit .env and insert your bot token from the Discord Developer Portal.")
        sys.exit(1)

    bot = AutoShopBot()
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot process interrupted by user. Shutting down.")
