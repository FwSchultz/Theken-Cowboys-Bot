from __future__ import annotations

import random
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from utils.permissions import admin_only, handle_app_command_error


class WelcomeChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog: "WelcomeCog", key: str, placeholder: str, row: int):
        self.cog = cog
        self.key = key
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=row)

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        self.cog.store.set(self.key, int(channel.id))
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=WelcomePanelView(self.cog))
        await interaction.followup.send(f"✅ Gespeichert: `{self.key}` → {channel.mention}", ephemeral=True)


class WelcomeTextModal(discord.ui.Modal):
    def __init__(self, cog: "WelcomeCog", section: str):
        super().__init__(title=f"{section.title()}-Text hinzufügen")
        self.cog = cog
        self.section = section
        self.text = discord.ui.TextInput(label="Text", style=discord.TextStyle.paragraph, max_length=1500, placeholder="Nutze {mention}, {name}, {server}")
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        key = f"{self.section}.messages"
        messages = list(self.cog.store.get(key, []) or [])
        messages.append(str(self.text.value))
        self.cog.store.set(key, messages)
        await interaction.response.send_message(f"✅ Text für `{self.section}` hinzugefügt. Anzahl: `{len(messages)}`", ephemeral=True)


class WelcomePanelView(discord.ui.View):
    def __init__(self, cog: "WelcomeCog"):
        super().__init__(timeout=300)
        self.cog = cog
        self.add_item(WelcomeChannelSelect(cog, "channel.welcome", "Welcome-Channel auswählen", 1))
        self.add_item(WelcomeChannelSelect(cog, "channel.leave", "Leave-Channel auswählen", 2))

    @discord.ui.button(label="Welcome an/aus", emoji="👋", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_welcome(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = bool(self.cog.store.get("welcome.enabled", True))
        self.cog.store.set("welcome.enabled", not current)
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=WelcomePanelView(self.cog))

    @discord.ui.button(label="Leave an/aus", emoji="🚪", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = bool(self.cog.store.get("leave.enabled", True))
        self.cog.store.set("leave.enabled", not current)
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=WelcomePanelView(self.cog))

    @discord.ui.button(label="Embed an/aus", emoji="🧾", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_w = bool(self.cog.store.get("welcome.use_embed", True))
        current_l = bool(self.cog.store.get("leave.use_embed", True))
        self.cog.store.set("welcome.use_embed", not current_w)
        self.cog.store.set("leave.use_embed", not current_l)
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=WelcomePanelView(self.cog))

    @discord.ui.button(label="Willkommen testen", emoji="🧪", style=discord.ButtonStyle.primary, row=3)
    async def test_welcome(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Fehler: Kein Member-Kontext erkannt.", ephemeral=True)
            return
        await self.cog.send_configured_message(interaction.user, "welcome")
        await interaction.response.send_message("✅ Test-Willkommensnachricht wurde gesendet.", ephemeral=True)

    @discord.ui.button(label="Verlassen testen", emoji="🧪", style=discord.ButtonStyle.secondary, row=3)
    async def test_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Fehler: Kein Member-Kontext erkannt.", ephemeral=True)
            return
        await self.cog.send_configured_message(interaction.user, "leave")
        await interaction.response.send_message("✅ Test-Verlassensnachricht wurde gesendet.", ephemeral=True)

    @discord.ui.button(label="Welcome-Text +", emoji="➕", style=discord.ButtonStyle.secondary, row=4)
    async def add_welcome_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WelcomeTextModal(self.cog, "welcome"))

    @discord.ui.button(label="Leave-Text +", emoji="➕", style=discord.ButtonStyle.secondary, row=4)
    async def add_leave_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WelcomeTextModal(self.cog, "leave"))

    @discord.ui.button(label="Aktualisieren", emoji="🔄", style=discord.ButtonStyle.secondary, row=4)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction), view=WelcomePanelView(self.cog))


class WelcomeCog(commands.Cog):
    welcome_group = app_commands.Group(name="welcome", description="Willkommen/Verlassen verwalten")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def store(self):
        return self.bot.settings

    def section_config(self, section_name: str) -> dict:
        yaml_cfg = dict(self.bot.config_data.get(section_name, {}))
        yaml_cfg["enabled"] = self.store.get(f"{section_name}.enabled", yaml_cfg.get("enabled", False))
        yaml_cfg["use_embed"] = self.store.get(f"{section_name}.use_embed", yaml_cfg.get("use_embed", True))
        yaml_cfg["channel_id"] = self.store.get(f"channel.{section_name}", yaml_cfg.get("channel_id"))
        yaml_cfg["title"] = self.store.get(f"{section_name}.title", yaml_cfg.get("title", "Theken-Cowboys"))
        yaml_cfg["color"] = self.store.get(f"{section_name}.color", yaml_cfg.get("color", "gold"))
        yaml_cfg["messages"] = self.store.get(f"{section_name}.messages", yaml_cfg.get("messages", [])) or []
        return yaml_cfg

    def get_color(self, color_name: str) -> discord.Color:
        colors = {
            "green": discord.Color.green(), "red": discord.Color.red(), "blue": discord.Color.blue(),
            "orange": discord.Color.orange(), "gold": discord.Color.gold(), "purple": discord.Color.purple(),
            "dark_red": discord.Color.dark_red(), "dark_green": discord.Color.dark_green(), "dark_blue": discord.Color.dark_blue(),
        }
        return colors.get(str(color_name).lower().strip(), discord.Color.gold())

    def format_message(self, template: str, member: discord.Member) -> str:
        return template.format(mention=member.mention, name=member.display_name, username=member.name, server=member.guild.name)

    def build_welcome_embed(self, member: discord.Member, title: str, text: str, color: discord.Color) -> discord.Embed:
        embed = discord.Embed(title=title, description=text, color=color, timestamp=datetime.now(timezone.utc))
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        embed.add_field(name="👥 Mitglied", value=f"#{member.guild.member_count}", inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"User-ID: {member.id}")
        return embed

    def build_leave_embed(self, member: discord.Member, title: str, text: str, color: discord.Color) -> discord.Embed:
        embed = discord.Embed(title=title, description=text, color=color, timestamp=datetime.now(timezone.utc))
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"User-ID: {member.id}")
        return embed

    async def send_configured_message(self, member: discord.Member, section_name: str) -> None:
        config = self.section_config(section_name)
        if not config.get("enabled", False):
            return
        channel_id = config.get("channel_id")
        messages = config.get("messages", [])
        if not channel_id or not messages:
            logging.warning("%s ist unvollständig konfiguriert.", section_name)
            return
        channel = member.guild.get_channel(int(channel_id))
        if not channel:
            logging.warning("Channel für %s nicht gefunden. Channel-ID: %s", section_name, channel_id)
            return
        template = random.choice(messages)
        text = self.format_message(template, member)
        use_embed = bool(config.get("use_embed", True))
        title = config.get("title", "Theken-Cowboys")
        color = self.get_color(config.get("color", "gold"))
        try:
            if not use_embed:
                await channel.send(text)
                return
            embed = self.build_welcome_embed(member, title, text, color) if section_name == "welcome" else self.build_leave_embed(member, title, text, color)
            await channel.send(embed=embed)
        except discord.Forbidden:
            logging.error("Keine Rechte zum Senden des %s-Embeds in Channel-ID: %s", section_name, channel_id)
        except discord.HTTPException as error:
            logging.error("Fehler beim Senden des %s-Embeds: %s", section_name, error)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.send_configured_message(member, "welcome")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self.send_configured_message(member, "leave")

    def build_panel_embed(self, interaction: discord.Interaction) -> discord.Embed:
        welcome = self.section_config("welcome")
        leave = self.section_config("leave")
        guild = interaction.guild
        def channel_line(section: dict) -> str:
            channel_id = section.get("channel_id")
            channel = guild.get_channel(int(channel_id)) if guild and channel_id else None
            return channel.mention if channel else f"`{channel_id or 0}`"
        embed = discord.Embed(title="👋 Welcome-Panel", description="Channel, Status und Texte werden in SQLite gespeichert.", color=discord.Color.gold())
        embed.add_field(
            name="Willkommen",
            value=(f"**Aktiv:** {'✅' if welcome.get('enabled') else '❌'}\n**Embed:** {'✅' if welcome.get('use_embed') else '❌'}\n**Channel:** {channel_line(welcome)}\n**Texte:** `{len(welcome.get('messages', []))}`"),
            inline=False,
        )
        embed.add_field(
            name="Verlassen",
            value=(f"**Aktiv:** {'✅' if leave.get('enabled') else '❌'}\n**Embed:** {'✅' if leave.get('use_embed') else '❌'}\n**Channel:** {channel_line(leave)}\n**Texte:** `{len(leave.get('messages', []))}`"),
            inline=False,
        )
        return embed

    @welcome_group.command(name="panel", description="Öffnet das Welcome-Bedienfeld.")
    @admin_only()
    async def welcome_panel(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self.build_panel_embed(interaction), view=WelcomePanelView(self), ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        handled = await handle_app_command_error(interaction, error)
        if handled:
            return
        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
