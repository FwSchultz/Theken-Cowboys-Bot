from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

from utils.permissions import admin_only, handle_app_command_error


class ArcRaiderCog(commands.Cog):
    arc_group = app_commands.Group(name="arc", description="ARC-Raider-Funktionen")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def store(self):
        return self.bot.settings

    def get_config(self) -> dict:
        return self.bot.config_data.get("arc_raider", {})

    def icon(self, value: bool) -> str:
        return "✅" if value else "❌"

    @arc_group.command(name="status", description="Zeigt den ARC-Raider Status.")
    @admin_only()
    async def status_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config = self.get_config()
        website = config.get("website", {}) if isinstance(config, dict) else {}

        tracker_channel_id = self.store.get("channel.autoclear", 0)
        tracker_channel = interaction.guild.get_channel(int(tracker_channel_id)) if interaction.guild and tracker_channel_id else None
        arc_role_id = self.store.get("role.arc_raider", 0)
        arc_role = interaction.guild.get_role(int(arc_role_id)) if interaction.guild and arc_role_id else None

        embed = discord.Embed(
            title="🛰️ ARC-Raider Status",
            description="ARC nutzt aktuell AutoClear für ARCTracker.io-Nachrichten und die Website-Verlinkung.",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="Tracker / AutoClear",
            value=(
                f"**Channel:** {tracker_channel.mention if tracker_channel else f'`{tracker_channel_id or 0}`'}\n"
                f"**AutoClear aktiv:** {self.icon(self.store.get('autoclear.enabled', False))}\n"
                f"**Ziel-Bot-ID:** `{self.store.get('autoclear.target_bot_user_id', 0)}`\n"
                f"**Dry-Run:** `{self.store.get('autoclear.dry_run', True)}`"
            ),
            inline=False,
        )
        embed.add_field(name="Rolle", value=f"ARC-Raider: {arc_role.mention if arc_role else f'`{arc_role_id or 0}`'}", inline=False)
        embed.add_field(
            name="Website",
            value=f"{self.icon(bool(website.get('enabled', False)))} `{website.get('url', 'https://arc.fwschultz.de')}`",
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @arc_group.command(name="website", description="Zeigt den ARC-Raider Website-Link.")
    async def website_command(self, interaction: discord.Interaction):
        config = self.get_config()
        website = config.get("website", {}) if isinstance(config, dict) else {}
        url = website.get("url", "https://arc.fwschultz.de")
        await interaction.response.send_message(f"🛰️ ARC-Raider Cache: {url}", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        handled = await handle_app_command_error(interaction, error)
        if handled:
            return
        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(ArcRaiderCog(bot))
