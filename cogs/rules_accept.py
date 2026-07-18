from __future__ import annotations

from datetime import datetime, timezone
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.permissions import admin_only, handle_app_command_error


class RulesAcceptView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    def get_config(self) -> dict:
        cog = self.bot.get_cog("RulesAcceptCog")
        if cog and hasattr(cog, "get_config"):
            return cog.get_config()
        return self.bot.config_data.get("rules_accept", {})

    async def notify_admins(self, guild: discord.Guild, member: discord.Member, interaction: discord.Interaction):
        config = self.get_config()
        text = (
            f"🍺 **Neuer Gast verfügbar**\n\n"
            f"**User:** {member.mention} / `{member.display_name}`\n"
            f"**User-ID:** `{member.id}`\n"
            f"**Server:** `{guild.name}`\n\n"
            f"Der User hat die Hausordnung bestätigt und wartet auf weitere Rechte."
        )
        notified = False
        for admin_user_id in config.get("notify_admin_user_ids", []):
            try:
                user = await self.bot.fetch_user(int(admin_user_id))
                await user.send(text)
                notified = True
            except Exception as error:
                logging.warning("Admin-PN konnte nicht gesendet werden | Admin-ID: %s | Fehler: %s", admin_user_id, error)
        admin_notify_channel_id = config.get("admin_notify_channel_id")
        if admin_notify_channel_id:
            channel = guild.get_channel(int(admin_notify_channel_id))
            if channel:
                try:
                    await channel.send(text)
                    notified = True
                except Exception as error:
                    logging.warning("Admin-Notify-Channel konnte nicht beschrieben werden | Channel-ID: %s | Fehler: %s", admin_notify_channel_id, error)
        if not notified:
            logging.warning("Kein Admin konnte über neuen Gast informiert werden | User-ID: %s", member.id)

    @discord.ui.button(label="Hausordnung akzeptieren", style=discord.ButtonStyle.success, custom_id="rules_accept:accept")
    async def accept_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = self.get_config()
        if not config.get("enabled", False):
            await interaction.response.send_message("❌ Die Hausordnungs-Bestätigung ist aktuell deaktiviert.", ephemeral=True)
            return
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Dieser Button kann nur auf dem Server genutzt werden.", ephemeral=True)
            return
        member = interaction.user
        guild = interaction.guild
        guest_role_id = config.get("guest_role_id")
        if not guest_role_id:
            await interaction.response.send_message("❌ Die Gast-Rolle ist nicht konfiguriert.", ephemeral=True)
            return
        role = guild.get_role(int(guest_role_id))
        if not role:
            await interaction.response.send_message("❌ Die konfigurierte Gast-Rolle wurde nicht gefunden.", ephemeral=True)
            return
        if role in member.roles:
            await interaction.response.send_message(config.get("already_accepted_message", "✅ Du hast die Hausordnung bereits bestätigt."), ephemeral=True)
            return
        try:
            await member.add_roles(role, reason="Hausordnung akzeptiert")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Ich darf diese Rolle nicht vergeben. Prüfe Rollen-Reihenfolge und Bot-Rechte.", ephemeral=True)
            return
        except Exception as error:
            logging.error("Gast-Rolle konnte nicht vergeben werden | User-ID: %s | Fehler: %s", member.id, error)
            await interaction.response.send_message("❌ Beim Vergeben der Gast-Rolle ist ein Fehler aufgetreten.", ephemeral=True)
            return
        await self.notify_admins(guild=guild, member=member, interaction=interaction)
        await interaction.response.send_message(config.get("success_message", "✅ Danke! Du hast die Hausordnung bestätigt und bist jetzt Gast."), ephemeral=True)


class RulesChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog: "RulesAcceptCog", key: str, placeholder: str, row: int):
        self.cog = cog
        self.key = key
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=row)

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        self.cog.store.set(self.key, int(channel.id))
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=RulesPanelView(self.cog))
        await interaction.followup.send(f"✅ Gespeichert: `{self.key}` → {channel.mention}", ephemeral=True)


class RulesGuestRoleSelect(discord.ui.RoleSelect):
    def __init__(self, cog: "RulesAcceptCog"):
        self.cog = cog
        super().__init__(placeholder="Gast-Rolle auswählen", min_values=1, max_values=1, row=3)

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        self.cog.store.set("role.guest", int(role.id))
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=RulesPanelView(self.cog))
        await interaction.followup.send(f"✅ Gast-Rolle gesetzt: {role.mention}", ephemeral=True)


class RulesTextModal(discord.ui.Modal, title="Hausordnungstext ändern"):
    description = discord.ui.TextInput(label="Beschreibung", style=discord.TextStyle.paragraph, max_length=3500)

    def __init__(self, cog: "RulesAcceptCog"):
        super().__init__()
        self.cog = cog
        self.description.default = str(cog.get_config().get("description", ""))[:3500]

    async def on_submit(self, interaction: discord.Interaction):
        self.cog.store.set("rules.description", str(self.description.value))
        await interaction.response.send_message("✅ Hausordnungstext gespeichert.", ephemeral=True)


class RulesPanelView(discord.ui.View):
    def __init__(self, cog: "RulesAcceptCog"):
        super().__init__(timeout=300)
        self.cog = cog
        self.add_item(RulesChannelSelect(cog, "channel.rules", "Hausordnung-Channel auswählen", 1))
        self.add_item(RulesChannelSelect(cog, "channel.admin_notify", "Admin-Notify-Channel auswählen", 2))
        self.add_item(RulesGuestRoleSelect(cog))

    @discord.ui.button(label="Aktiv an/aus", emoji="📜", style=discord.ButtonStyle.secondary, row=0)
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = bool(self.cog.store.get("rules.enabled", True))
        self.cog.store.set("rules.enabled", not current)
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=RulesPanelView(self.cog))

    @discord.ui.button(label="Hausordnung posten", emoji="📨", style=discord.ButtonStyle.primary, row=0)
    async def post(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.post_rules(interaction)

    @discord.ui.button(label="Text ändern", emoji="✏️", style=discord.ButtonStyle.secondary, row=0)
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RulesTextModal(self.cog))

    @discord.ui.button(label="Aktualisieren", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=RulesPanelView(self.cog))


class RulesAcceptCog(commands.Cog):
    rules_group = app_commands.Group(name="rules", description="Hausordnung und Freischaltung")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def store(self):
        return self.bot.settings

    def get_config(self) -> dict:
        yaml_cfg = dict(self.bot.config_data.get("rules_accept", {}))
        yaml_cfg["enabled"] = self.store.get("rules.enabled", yaml_cfg.get("enabled", False))
        yaml_cfg["channel_id"] = self.store.get("channel.rules", yaml_cfg.get("channel_id"))
        yaml_cfg["admin_notify_channel_id"] = self.store.get("channel.admin_notify", yaml_cfg.get("admin_notify_channel_id"))
        yaml_cfg["guest_role_id"] = self.store.get("role.guest", yaml_cfg.get("guest_role_id"))
        yaml_cfg["title"] = self.store.get("rules.title", yaml_cfg.get("title", "📜 Hausordnung"))
        yaml_cfg["description"] = self.store.get("rules.description", yaml_cfg.get("description", "Bitte bestätige die Hausordnung."))
        yaml_cfg["button_label"] = self.store.get("rules.button_label", yaml_cfg.get("button_label", "✅ Hausordnung akzeptieren"))
        yaml_cfg["success_message"] = self.store.get("rules.success_message", yaml_cfg.get("success_message", "✅ Danke! Du hast die Hausordnung bestätigt und bist jetzt Gast."))
        yaml_cfg["already_accepted_message"] = self.store.get("rules.already_accepted_message", yaml_cfg.get("already_accepted_message", "✅ Du hast die Hausordnung bereits bestätigt."))
        yaml_cfg["notify_admin_user_ids"] = self.store.get("rules.notify_admin_user_ids", yaml_cfg.get("notify_admin_user_ids", [])) or []
        return yaml_cfg

    def build_rules_embed(self) -> discord.Embed:
        config = self.get_config()
        embed = discord.Embed(title=config.get("title", "📜 Hausordnung"), description=config.get("description", "Bitte bestätige die Hausordnung."), color=discord.Color.gold(), timestamp=datetime.now(timezone.utc))
        embed.set_footer(text="Theken-Cowboys · Bitte bestätigen, um Gast zu werden")
        return embed

    def build_panel_embed(self, interaction: discord.Interaction) -> discord.Embed:
        config = self.get_config()
        guild = interaction.guild
        channel = guild.get_channel(int(config.get("channel_id"))) if guild and config.get("channel_id") else None
        notify = guild.get_channel(int(config.get("admin_notify_channel_id"))) if guild and config.get("admin_notify_channel_id") else None
        role = guild.get_role(int(config.get("guest_role_id"))) if guild and config.get("guest_role_id") else None
        embed = discord.Embed(
            title="📜 Rules-Panel",
            description=(
                "Hausordnung, Gast-Rolle und Notify-Channel werden in SQLite gespeichert.\n\n"
                "**Gast-Rolle:** Diese Rolle bekommt ein User automatisch, nachdem er die Hausordnung per Button akzeptiert hat. "
                "Damit kannst du neue User erst eingeschränkt lassen und sie nach Bestätigung für normale Bereiche freischalten."
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(name="Status", value="✅ Aktiv" if config.get("enabled") else "❌ Deaktiviert", inline=True)
        embed.add_field(name="Hausordnung-Channel", value=channel.mention if channel else f"`{config.get('channel_id') or 0}`", inline=False)
        embed.add_field(name="Gast-Rolle", value=(role.mention if role else f"`{config.get('guest_role_id') or 0}`") + "\nWird nach Klick auf den Hausordnung-Button vergeben.", inline=False)
        embed.add_field(name="Admin-Notify", value=notify.mention if notify else f"`{config.get('admin_notify_channel_id') or 0}`", inline=False)
        embed.add_field(name="Button", value=str(config.get("button_label", "Hausordnung akzeptieren")), inline=False)
        return embed

    async def post_rules(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("❌ Dieser Befehl kann nur auf einem Server genutzt werden.", ephemeral=True)
            return
        config = self.get_config()
        if not config.get("enabled", False):
            await interaction.response.send_message("❌ Hausordnung ist deaktiviert.", ephemeral=True)
            return
        channel_id = config.get("channel_id")
        if not channel_id:
            await interaction.response.send_message("❌ Hausordnung-Channel fehlt. Im Panel auswählen.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(int(channel_id))
        if not channel:
            await interaction.response.send_message("❌ Hausordnung-Channel wurde nicht gefunden.", ephemeral=True)
            return
        view = RulesAcceptView(self.bot)
        if config.get("button_label"):
            view.children[0].label = config.get("button_label")
        await channel.send(embed=self.build_rules_embed(), view=view)
        await interaction.response.send_message(f"✅ Hausordnung wurde in {channel.mention} gepostet.", ephemeral=True)

    @rules_group.command(name="panel", description="Öffnet das Hausordnung-Bedienfeld.")
    @admin_only()
    async def rules_panel(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self.build_panel_embed(interaction), view=RulesPanelView(self), ephemeral=True)

    # Fallback bleibt absichtlich als einzelner Befehl sichtbar, weil Setup oft gebraucht wird.
    @rules_group.command(name="setup", description="Postet die Hausordnung mit Bestätigungs-Button.")
    @admin_only()
    async def rules_setup_command(self, interaction: discord.Interaction):
        await self.post_rules(interaction)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        handled = await handle_app_command_error(interaction, error)
        if handled:
            return
        raise error


async def setup(bot: commands.Bot):
    bot.add_view(RulesAcceptView(bot))
    await bot.add_cog(RulesAcceptCog(bot))
