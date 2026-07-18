import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.permissions import admin_only, handle_app_command_error


class MemberLogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog: "MemberLoggerCog"):
        self.cog = cog
        super().__init__(placeholder="Memberlog-Channel auswählen", min_values=1, max_values=1, channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=3)

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        self.cog.bot.settings.set("channel.memberlog", int(channel.id))
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=MemberLogPanelView(self.cog))
        await interaction.followup.send(f"✅ Memberlog-Channel gesetzt: {channel.mention}", ephemeral=True)


class MemberLogTrackedRoleSelect(discord.ui.RoleSelect):
    def __init__(self, cog: "MemberLoggerCog"):
        self.cog = cog
        super().__init__(placeholder="Tracked-Rolle hinzufügen/entfernen", min_values=1, max_values=1, row=4)

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        ids = list(self.cog.bot.settings.get("memberlog.tracked_role_ids", []) or [])
        ids = [int(x) for x in ids]
        if role.id in ids:
            ids = [x for x in ids if x != role.id]
            msg = f"✅ Tracked-Rolle entfernt: {role.mention}"
        else:
            ids.append(role.id)
            msg = f"✅ Tracked-Rolle hinzugefügt: {role.mention}"
        self.cog.bot.settings.set("memberlog.tracked_role_ids", ids)
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=MemberLogPanelView(self.cog))
        await interaction.followup.send(msg, ephemeral=True)


class MemberLogCleanupModal(discord.ui.Modal, title="Memberlog-Cleanup einstellen"):
    interval_hours = discord.ui.TextInput(label="Intervall Stunden", default="24", max_length=4)
    delete_after_hours = discord.ui.TextInput(label="Löschen nach Stunden", default="48", max_length=4)
    scan_limit = discord.ui.TextInput(label="Scan-Limit", default="500", max_length=5)

    def __init__(self, cog: "MemberLoggerCog"):
        super().__init__()
        self.cog = cog
        store = cog.bot.settings
        self.interval_hours.default = str(store.get("memberlog.cleanup.interval_hours", 24))
        self.delete_after_hours.default = str(store.get("memberlog.cleanup.delete_after_hours", 48))
        self.scan_limit.default = str(store.get("memberlog.cleanup.scan_limit", 500))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            interval = int(str(self.interval_hours.value).strip())
            delete_after = int(str(self.delete_after_hours.value).strip())
            scan_limit = int(str(self.scan_limit.value).strip())
        except ValueError:
            await interaction.response.send_message("❌ Werte müssen Zahlen sein.", ephemeral=True)
            return
        self.cog.bot.settings.set("memberlog.cleanup.interval_hours", max(1, interval))
        self.cog.bot.settings.set("memberlog.cleanup.delete_after_hours", max(1, delete_after))
        self.cog.bot.settings.set("memberlog.cleanup.scan_limit", max(1, scan_limit))
        await interaction.response.send_message("✅ Memberlog-Cleanup gespeichert.", ephemeral=True)


class MemberLogPanelView(discord.ui.View):
    def __init__(self, cog: "MemberLoggerCog"):
        super().__init__(timeout=300)
        self.cog = cog
        self.add_item(MemberLogChannelSelect(cog))
        self.add_item(MemberLogTrackedRoleSelect(cog))

    @discord.ui.button(label="Test senden", emoji="🧪", style=discord.ButtonStyle.primary, row=0)
    async def test(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Fehler: Kein Member-Kontext erkannt.", ephemeral=True)
            return
        if not self.cog.is_enabled():
            await interaction.response.send_message("Member-Logger ist deaktiviert.", ephemeral=True)
            return
        await self.cog.send_log_line(
            interaction.guild,
            f"🧪 **{interaction.user.display_name}** hat den Member-Logger getestet | `{self.cog.format_time()}` | 🔊 **TEST-CHANNEL**",
        )
        await interaction.response.send_message("✅ Testzeile wurde im Member-Log-Channel gesendet.", ephemeral=True)

    @discord.ui.button(label="Cleanup starten", emoji="🧹", style=discord.ButtonStyle.danger, row=0)
    async def cleanup(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        result = await self.cog.cleanup_memberlog_channel()
        await interaction.followup.send(
            "**Memberlog-Cleanup abgeschlossen.**\n"
            f"Geprüft: `{result['checked']}`\n"
            f"Gelöscht: `{result['deleted']}`\n"
            f"Fehler: `{result['errors']}`",
            ephemeral=True,
        )

    @discord.ui.button(label="Aktiv an/aus", emoji="🌐", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_enabled(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = bool(self.cog.bot.settings.get("memberlog.enabled", True))
        self.cog.bot.settings.set("memberlog.enabled", not current)
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=MemberLogPanelView(self.cog))

    @discord.ui.button(label="Voice Join", emoji="🟢", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = bool(self.cog.bot.settings.get("memberlog.event.voice_join", True))
        self.cog.bot.settings.set("memberlog.event.voice_join", not current)
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=MemberLogPanelView(self.cog))

    @discord.ui.button(label="Voice Leave", emoji="🔴", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = bool(self.cog.bot.settings.get("memberlog.event.voice_leave", True))
        self.cog.bot.settings.set("memberlog.event.voice_leave", not current)
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=MemberLogPanelView(self.cog))

    @discord.ui.button(label="Cleanup an/aus", emoji="🧹", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_cleanup_enabled(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = bool(self.cog.bot.settings.get("memberlog.cleanup.enabled", True))
        self.cog.bot.settings.set("memberlog.cleanup.enabled", not current)
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=MemberLogPanelView(self.cog))

    @discord.ui.button(label="Cleanup einstellen", emoji="⚙️", style=discord.ButtonStyle.secondary, row=2)
    async def cleanup_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MemberLogCleanupModal(self.cog))

    @discord.ui.button(label="Aktualisieren", emoji="🔄", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=MemberLogPanelView(self.cog))


class MemberLoggerCog(commands.Cog):
    memberlog_group = app_commands.Group(name="memberlog", description="Voice-/Member-Log verwalten")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.memberlog_cleanup_loop.start()

    def cog_unload(self):
        self.memberlog_cleanup_loop.cancel()

    def get_config(self) -> dict:
        cfg = dict(self.bot.config_data.get("member_logger", {}))
        cfg["enabled"] = self.bot.settings.get("memberlog.enabled", cfg.get("enabled", False))
        cfg["log_channel_id"] = self.bot.settings.get("channel.memberlog", cfg.get("log_channel_id"))
        cfg["tracked_role_ids"] = self.bot.settings.get("memberlog.tracked_role_ids", cfg.get("tracked_role_ids", [])) or []
        cfg["events"] = self.get_events_config()
        cfg["cleanup"] = self.get_cleanup_config()
        return cfg

    def get_events_config(self) -> dict:
        yaml_events = self.bot.config_data.get("member_logger", {}).get("events", {})
        return {
            "voice_join": self.bot.settings.get("memberlog.event.voice_join", yaml_events.get("voice_join", True)),
            "voice_leave": self.bot.settings.get("memberlog.event.voice_leave", yaml_events.get("voice_leave", True)),
            "voice_switch": self.bot.settings.get("memberlog.event.voice_switch", yaml_events.get("voice_switch", False)),
            "server_leave": self.bot.settings.get("memberlog.event.server_leave", yaml_events.get("server_leave", True)),
        }

    def get_cleanup_config(self) -> dict:
        yaml_cleanup = self.bot.config_data.get("member_logger", {}).get("cleanup", {})
        return {
            "enabled": self.bot.settings.get("memberlog.cleanup.enabled", yaml_cleanup.get("enabled", False)),
            "interval_hours": self.bot.settings.get("memberlog.cleanup.interval_hours", yaml_cleanup.get("interval_hours", 24)),
            "delete_after_hours": self.bot.settings.get("memberlog.cleanup.delete_after_hours", yaml_cleanup.get("delete_after_hours", 24)),
            "scan_limit": self.bot.settings.get("memberlog.cleanup.scan_limit", yaml_cleanup.get("scan_limit", 500)),
        }

    def get_logging_config(self) -> dict:
        return self.bot.config_data.get("logging", {})

    def is_enabled(self) -> bool:
        return bool(self.get_config().get("enabled", False))

    def verbose_memberlog(self) -> bool:
        return bool(self.get_logging_config().get("verbose_memberlog", False))

    def get_log_channel(self, guild: discord.Guild):
        channel_id = self.get_config().get("log_channel_id")

        if not channel_id:
            return None

        return guild.get_channel(int(channel_id))

    def has_tracked_role(self, member: discord.Member) -> bool:
        role_ids = self.get_config().get("tracked_role_ids", [])

        if not role_ids:
            return False

        tracked_role_ids = {int(role_id) for role_id in role_ids}
        member_role_ids = {role.id for role in member.roles}

        return bool(tracked_role_ids.intersection(member_role_ids))

    def format_time(self) -> str:
        return datetime.now(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M")

    def get_member_name(self, member: discord.Member) -> str:
        return member.display_name

    async def send_log_line(self, guild: discord.Guild, text: str):
        channel = self.get_log_channel(guild)

        if not channel:
            logging.warning("Member-Logger: Log-Channel nicht gefunden.")
            return

        try:
            await channel.send(text)
        except discord.Forbidden:
            logging.error("Member-Logger: Keine Rechte zum Schreiben in den Log-Channel.")
        except discord.HTTPException as error:
            logging.error("Member-Logger: Fehler beim Schreiben in den Log-Channel: %s", error)

    async def log_voice_join(self, member: discord.Member, channel: discord.VoiceChannel):
        text = (
            f"🟢 **{self.get_member_name(member)}** ist Voice beigetreten "
            f"| `{self.format_time()}` "
            f"| 🔊 **{channel.name}**"
        )

        await self.send_log_line(member.guild, text)

    async def log_voice_leave(self, member: discord.Member, channel: discord.VoiceChannel):
        text = (
            f"🔴 **{self.get_member_name(member)}** hat Voice verlassen "
            f"| `{self.format_time()}` "
            f"| 🔊 **{channel.name}**"
        )

        await self.send_log_line(member.guild, text)

    async def log_voice_switch(
        self,
        member: discord.Member,
        before_channel: discord.VoiceChannel,
        after_channel: discord.VoiceChannel,
    ):
        text = (
            f"🔁 **{self.get_member_name(member)}** hat Voice gewechselt "
            f"| `{self.format_time()}` "
            f"| 🔊 **{before_channel.name}** → 🔊 **{after_channel.name}**"
        )

        await self.send_log_line(member.guild, text)

    async def log_server_leave(self, member: discord.Member):
        text = (
            f"🚪 **{self.get_member_name(member)}** hat den Server verlassen "
            f"| `{self.format_time()}` "
            f"| User-ID: `{member.id}`"
        )

        await self.send_log_line(member.guild, text)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if not self.is_enabled():
            return

        if member.bot:
            return

        if not self.has_tracked_role(member):
            return

        events = self.get_events_config()

        # Voice betreten
        if before.channel is None and after.channel is not None:
            if not events.get("voice_join", True):
                return

            await self.log_voice_join(member, after.channel)
            return

        # Voice verlassen
        if before.channel is not None and after.channel is None:
            if not events.get("voice_leave", True):
                return

            await self.log_voice_leave(member, before.channel)
            return

        # Voice gewechselt
        if before.channel is not None and after.channel is not None:
            if before.channel.id == after.channel.id:
                return

            if not events.get("voice_switch", False):
                return

            await self.log_voice_switch(member, before.channel, after.channel)
            return

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if not self.is_enabled():
            return

        if member.bot:
            return

        if not self.has_tracked_role(member):
            return

        events = self.get_events_config()

        if not events.get("server_leave", True):
            return

        await self.log_server_leave(member)

    async def cleanup_memberlog_channel(self) -> dict:
        config = self.get_config()

        if not config.get("enabled", False):
            return {
                "enabled": False,
                "checked": 0,
                "deleted": 0,
                "errors": 0,
            }

        cleanup_config = self.get_cleanup_config()

        if not cleanup_config.get("enabled", False):
            return {
                "enabled": False,
                "checked": 0,
                "deleted": 0,
                "errors": 0,
            }

        guild_id = self.bot.config_data.get("guild", {}).get("id")
        guild = self.bot.get_guild(int(guild_id)) if guild_id else None

        if not guild:
            logging.warning("Memberlog-Cleanup: Guild nicht gefunden.")
            return {
                "enabled": True,
                "checked": 0,
                "deleted": 0,
                "errors": 1,
            }

        channel = self.get_log_channel(guild)

        if not channel:
            logging.warning("Memberlog-Cleanup: Log-Channel nicht gefunden.")
            return {
                "enabled": True,
                "checked": 0,
                "deleted": 0,
                "errors": 1,
            }

        delete_after_hours = int(cleanup_config.get("delete_after_hours", 24))
        scan_limit = int(cleanup_config.get("scan_limit", 500))

        now = datetime.now(timezone.utc)
        max_age = timedelta(hours=delete_after_hours)

        checked = 0
        deleted = 0
        errors = 0

        try:
            async for message in channel.history(limit=scan_limit):
                checked += 1

                last_activity = message.edited_at or message.created_at

                if now - last_activity < max_age:
                    continue

                try:
                    await message.delete()
                    deleted += 1

                    if self.verbose_memberlog():
                        logging.info(
                            "Memberlog-Cleanup gelöscht | Message-ID: %s",
                            message.id,
                        )

                except discord.Forbidden:
                    errors += 1
                    logging.error(
                        "Memberlog-Cleanup: Keine Rechte zum Löschen von Message-ID: %s",
                        message.id,
                    )
                except discord.HTTPException as error:
                    errors += 1
                    logging.error(
                        "Memberlog-Cleanup: HTTP-Fehler bei Message-ID %s: %s",
                        message.id,
                        error,
                    )

        except discord.Forbidden:
            errors += 1
            logging.error(
                "Memberlog-Cleanup: Kein Zugriff auf den Log-Channel. "
                "Prüfe View Channel, Read Message History und Manage Messages."
            )
        except discord.HTTPException as error:
            errors += 1
            logging.error(
                "Memberlog-Cleanup: HTTP-Fehler beim Lesen des Log-Channels: %s",
                error,
            )

        return {
            "enabled": True,
            "checked": checked,
            "deleted": deleted,
            "errors": errors,
        }

    @tasks.loop(hours=24)
    async def memberlog_cleanup_loop(self):
        config = self.get_config()
        cleanup_config = self.get_cleanup_config()

        if not config.get("enabled", False):
            return

        if not cleanup_config.get("enabled", False):
            return

        interval_hours = int(cleanup_config.get("interval_hours", 24))

        if self.memberlog_cleanup_loop.hours != interval_hours:
            self.memberlog_cleanup_loop.change_interval(hours=interval_hours)

        result = await self.cleanup_memberlog_channel()
        logging.info("Memberlog-Cleanup abgeschlossen: %s", result)

    @memberlog_cleanup_loop.before_loop
    async def before_memberlog_cleanup_loop(self):
        await self.bot.wait_until_ready()


    def build_panel_embed(self, interaction: discord.Interaction) -> discord.Embed:
        config = self.get_config()
        cleanup = self.get_cleanup_config()
        events = self.get_events_config()
        channel = self.get_log_channel(interaction.guild) if interaction.guild else None
        embed = discord.Embed(title="🌐 Memberlog-Panel", description="Hier stellst du ein, welche Voice-/Member-Ereignisse in welchen Log-Kanal geschrieben werden. Tracked-Rollen begrenzen das Logging auf bestimmte Rollen.", color=discord.Color.green())
        tracked = []
        if interaction.guild:
            for role_id in config.get('tracked_role_ids', []) or []:
                role = interaction.guild.get_role(int(role_id))
                tracked.append(role.mention if role else f'`{role_id}`')
        embed.add_field(
            name="Member-Logger",
            value=(
                f"**Aktiv:** {'✅' if config.get('enabled') else '❌'}\n"
                f"**Log-Channel:** {channel.mention if channel else f'`{config.get('log_channel_id', 0)}`'}\n"
                f"**Tracked-Rollen:** {', '.join(tracked) if tracked else '`keine`'}"
            ),
            inline=False,
        )
        embed.add_field(
            name="Events",
            value=(
                f"Voice Join: {'✅' if events.get('voice_join') else '❌'}\n"
                f"Voice Leave: {'✅' if events.get('voice_leave') else '❌'}\n"
                f"Voice Switch: {'✅' if events.get('voice_switch') else '❌'}\n"
                f"Server Leave: {'✅' if events.get('server_leave') else '❌'}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Cleanup",
            value=(
                f"**Aktiv:** {'✅' if cleanup.get('enabled') else '❌'}\n"
                f"**Intervall:** `{cleanup.get('interval_hours', 24)} Stunden`\n"
                f"**Löschen nach:** `{cleanup.get('delete_after_hours', 24)} Stunden`\n"
                f"**Scan-Limit:** `{cleanup.get('scan_limit', 500)}`"
            ),
            inline=True,
        )
        return embed

    @memberlog_group.command(name="panel", description="Öffnet das Memberlog-Bedienfeld.")
    @admin_only()
    async def memberlog_panel(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self.build_panel_embed(interaction), view=MemberLogPanelView(self), ephemeral=True)

    # ausgeblendet: @memberlog_group.command(name="test", description="Sendet eine Testzeile in den Member-Log.")
    @admin_only()
    async def memberlog_test(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Fehler: Kein Member-Kontext erkannt.",
                ephemeral=True,
            )
            return

        if not self.is_enabled():
            await interaction.response.send_message(
                "Member-Logger ist in der den YAML-Configs deaktiviert.",
                ephemeral=True,
            )
            return

        await self.send_log_line(
            interaction.guild,
            (
                f"🧪 **{interaction.user.display_name}** hat den Member-Logger getestet "
                f"| `{self.format_time()}` "
                f"| 🔊 **TEST-CHANNEL**"
            ),
        )

        await interaction.response.send_message(
            "Testzeile wurde im Member-Log-Channel gesendet.",
            ephemeral=True,
        )

    # ausgeblendet: @memberlog_group.command(name="cleanup", description="Löscht alte Nachrichten aus dem Member-Log.")
    @admin_only()
    async def memberlog_cleanup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        result = await self.cleanup_memberlog_channel()

        await interaction.followup.send(
            (
                "**Memberlog-Cleanup abgeschlossen.**\n"
                f"Geprüft: `{result['checked']}`\n"
                f"Gelöscht: `{result['deleted']}`\n"
                f"Fehler: `{result['errors']}`"
            ),
            ephemeral=True,
        )

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        handled = await handle_app_command_error(interaction, error)

        if handled:
            return

        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(MemberLoggerCog(bot))