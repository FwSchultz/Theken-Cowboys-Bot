import asyncio
import logging
import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

from utils.config_loader import load_config, get_enabled_cogs
from services.logging_setup import setup_logging
from services.settings_store import SettingsStore


class ThekenCowboysBot(commands.Bot):
    def __init__(self, config: dict):
        self.config_data = config

        db_path = config.get("database", {}).get("path", "data/settings.sqlite")
        self.settings = SettingsStore(db_path)
        self.settings.seed_from_config(config)

        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True
        intents.voice_states = True

        prefix = config.get("bot", {}).get("command_prefix", "!")
        super().__init__(command_prefix=prefix, intents=intents)

    async def setup_hook(self) -> None:
        for extension in get_enabled_cogs(self.config_data):
            await self.load_extension(extension)
            logging.info("Cog geladen: %s", extension)

        guild_id = self.config_data.get("guild", {}).get("id") or os.getenv("GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logging.info("Slash-Commands für Guild %s synchronisiert: %s", guild_id, len(synced))
        else:
            synced = await self.tree.sync()
            logging.info("Globale Slash-Commands synchronisiert: %s", len(synced))

    async def on_ready(self) -> None:
        logging.info("Bot online als %s | ID: %s", self.user, self.user.id)
        logging.info("Logdateien aktiv: logs/bot.log und logs/error.log")


async def main() -> None:
    setup_logging(log_dir="logs")
    load_dotenv()

    token = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN fehlt in der .env")

    bot = ThekenCowboysBot(config=load_config())
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
