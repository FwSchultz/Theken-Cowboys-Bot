import logging
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

from utils.permissions import admin_only, handle_app_command_error
from utils.config_loader import load_config


class AdminCog(commands.Cog):
    admin_group = app_commands.Group(name="admin", description="Bot-Verwaltung und Status")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def bool_icon(self, value: bool) -> str:
        return "✅" if value else "❌"

    def get_channel_status(self, guild: discord.Guild, channel_id) -> str:
        if not channel_id:
            return "❌ nicht gesetzt"

        channel = guild.get_channel(int(channel_id))

        if not channel:
            return f"❌ nicht gefunden (`{channel_id}`)"

        return f"✅ {channel.mention}"

    def get_config_bool(self, section: str, key: str = "enabled") -> bool:
        return bool(self.bot.config_data.get(section, {}).get(key, False))

    @admin_group.command(
        name="status",
        description="Zeigt den aktuellen Status des Bots.",
    )
    @admin_only()
    async def status_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild:
            await interaction.followup.send(
                "Fehler: Dieser Befehl kann nur auf einem Server genutzt werden.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        config = self.bot.config_data

        welcome_config = config.get("welcome", {})
        leave_config = config.get("leave", {})
        autoclear_config = config.get("autoclear", {})
        member_logger_config = config.get("member_logger", {})
        permissions_config = config.get("permissions", {})
        modules_config = config.get("modules", {})

        latency_ms = round(self.bot.latency * 1000)

        embed = discord.Embed(
            title="🤠 Theken-Cowboys Bot Status",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="🤖 Bot",
            value=(
                f"**Status:** ✅ Online\n"
                f"**Name:** {self.bot.user}\n"
                f"**Ping:** `{latency_ms} ms`"
            ),
            inline=False,
        )

        embed.add_field(
            name="🍻 Welcome / Leave",
            value=(
                f"**Welcome:** {self.bool_icon(welcome_config.get('enabled', False))}\n"
                f"**Welcome Embed:** {self.bool_icon(welcome_config.get('use_embed', False))}\n"
                f"**Welcome Channel:** {self.get_channel_status(guild, welcome_config.get('channel_id'))}\n\n"
                f"**Leave:** {self.bool_icon(leave_config.get('enabled', False))}\n"
                f"**Leave Embed:** {self.bool_icon(leave_config.get('use_embed', False))}\n"
                f"**Leave Channel:** {self.get_channel_status(guild, leave_config.get('channel_id'))}"
            ),
            inline=False,
        )

        embed.add_field(
            name="🧹 Autoclear",
            value=(
                f"**Aktiv:** {self.bool_icon(autoclear_config.get('enabled', False))}\n"
                f"**Dry-Run:** {self.bool_icon(autoclear_config.get('dry_run', True))}\n"
                f"**Channel:** {self.get_channel_status(guild, autoclear_config.get('channel_id'))}\n"
                f"**Intervall:** `{autoclear_config.get('interval_minutes', 'n/a')} Minuten`\n"
                f"**Löschen nach:** `{autoclear_config.get('delete_after_minutes', 'n/a')} Minuten`\n"
                f"**Scan-Limit:** `{autoclear_config.get('scan_limit', 'n/a')}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎙️ Member-Logger",
            value=(
                f"**Aktiv:** {self.bool_icon(member_logger_config.get('enabled', False))}\n"
                f"**Log-Channel:** {self.get_channel_status(guild, member_logger_config.get('log_channel_id'))}\n"
                f"**Single Message/User:** {self.bool_icon(member_logger_config.get('single_message_per_user', True))}\n"
                f"**Voice Join:** {self.bool_icon(member_logger_config.get('events', {}).get('voice_join', False))}\n"
                f"**Voice Leave:** {self.bool_icon(member_logger_config.get('events', {}).get('voice_leave', False))}\n"
                f"**Voice Switch:** {self.bool_icon(member_logger_config.get('events', {}).get('voice_switch', False))}\n"
                f"**Server Leave:** {self.bool_icon(member_logger_config.get('events', {}).get('server_leave', False))}"
            ),
            inline=False,
        )

        cleanup_config = member_logger_config.get("cleanup", {})

        embed.add_field(
            name="🗑️ Memberlog-Cleanup",
            value=(
                f"**Aktiv:** {self.bool_icon(cleanup_config.get('enabled', False))}\n"
                f"**Intervall:** `{cleanup_config.get('interval_hours', 'n/a')} Stunden`\n"
                f"**Löschen nach:** `{cleanup_config.get('delete_after_hours', 'n/a')} Stunden`\n"
                f"**Scan-Limit:** `{cleanup_config.get('scan_limit', 'n/a')}`"
            ),
            inline=False,
        )


        if isinstance(modules_config, dict):
            module_lines = []
            for name, module in modules_config.items():
                if not isinstance(module, dict):
                    continue
                icon = self.bool_icon(bool(module.get("enabled", False)))
                cfg_file = module.get("config") or "-"
                module_lines.append(f"{icon} **{name}** → `{cfg_file}`")
            if module_lines:
                embed.add_field(
                    name="🧩 Module",
                    value="\n".join(module_lines[:12]),
                    inline=False,
                )

        admin_roles = permissions_config.get("admin_role_ids", [])
        allow_admin = permissions_config.get("allow_discord_administrator", True)

        embed.add_field(
            name="🔐 Admin-Check",
            value=(
                f"**Discord Administrator erlaubt:** {self.bool_icon(allow_admin)}\n"
                f"**Admin-Rollen gesetzt:** `{len(admin_roles)}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="🧾 Logs",
            value="`logs/bot.log` für normale Logs\n`logs/error.log` für Fehler",
            inline=False,
        )

        embed.set_footer(text=f"Guild-ID: {guild.id}")

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        handled = await handle_app_command_error(interaction, error)

        if handled:
            return

        raise error




    @admin_group.command(
        name="reload",
        description="Lädt alle YAML-Configs neu, ohne den Bot neu zu starten.",
    )
    @admin_only()
    async def reload_config_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            self.bot.config_data = load_config()
            self.bot.settings.seed_from_config(self.bot.config_data)
        except Exception as error:
            logging.error("Config-Reload fehlgeschlagen: %s", error)
            embed = discord.Embed(
                title="❌ Config-Reload fehlgeschlagen",
                description=f"Die YAML-Configs unter `config/` konnten nicht neu geladen werden.\n\n**Fehler:** `{error}`",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc),
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        embed = discord.Embed(
            title="✅ Config neu geladen",
            description=(
                "Die YAML-Configs unter `config/` wurden erfolgreich neu geladen.\n\n"
                "Wirksam sind Konfig-Werte wie Texte, IDs, Farben, Zeiten und Admin-Rollen. "
                "Änderungen an `config/main.yaml -> modules` brauchen weiterhin einen Neustart, weil Cogs/Slash-Commands neu geladen werden müssen."
            ),
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
