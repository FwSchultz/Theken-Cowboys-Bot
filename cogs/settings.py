from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils.permissions import admin_only, handle_app_command_error


ALLOWED_VALUE_KEYS = {
    "autoclear.schedule_mode": str,
    "autoclear.schedule_times": str,
    "autoclear.timezone": str,
    "autoclear.interval_minutes": int,
    "autoclear.delete_after_minutes": int,
    "autoclear.scan_limit": int,
    "autoclear.dry_run": bool,
    "autoclear.enabled": bool,
}



CHANNEL_SETTING_OPTIONS = [
    ("channel.welcome", "Welcome-Channel", "👋"),
    ("channel.leave", "Leave-Channel", "🚪"),
    ("channel.rules", "Hausordnung-Channel", "📜"),
    ("channel.admin_notify", "Admin-Notify-Channel", "🔔"),
    ("channel.memberlog", "Memberlog-Channel", "🧾"),
    ("channel.autoclear", "AutoClear-Channel", "🧹"),
    ("channel.translator_target", "Translator-Zielkanal", "🌐"),
]

ROLE_SETTING_OPTIONS = [
    ("role.guest", "Gast-Rolle", "🚪"),
    ("role.arc_raider", "ARC-Raider-Rolle", "🛰️"),
    ("role.admin", "Admin-/Wirt-Rolle", "🔐"),
]

MODULE_OPTIONS = [
    ("admin", "Admin", "🔐"),
    ("settings", "Settings", "⚙️"),
    ("welcome", "Welcome", "👋"),
    ("rules", "Hausordnung", "📜"),
    ("memberlog", "Memberlog", "🧾"),
    ("autoclear", "AutoClear", "🧹"),
    ("audit", "Audit", "🔎"),
    ("translator", "Translator", "🌐"),
    ("channel_tools", "Channel-Clear", "🧨"),
    ("arc_raider", "ARC-Raider", "🛰️"),
]


class SettingsModuleNameSelect(discord.ui.Select):
    def __init__(self, view: "SettingsModuleConfigView"):
        self.config_view = view
        options = [
            discord.SelectOption(label=label, value=name, emoji=emoji)
            for name, label, emoji in MODULE_OPTIONS
        ]
        super().__init__(placeholder="Modul auswählen ...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.config_view.selected_module = self.values[0]
        await interaction.response.edit_message(embed=self.config_view.build_embed(), view=self.config_view)


class SettingsModuleStatusSelect(discord.ui.Select):
    def __init__(self, view: "SettingsModuleConfigView"):
        self.config_view = view
        options = [
            discord.SelectOption(label="Aktivieren", value="on", emoji="✅"),
            discord.SelectOption(label="Deaktivieren", value="off", emoji="❌"),
        ]
        super().__init__(placeholder="Status auswählen ...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if not self.config_view.selected_module:
            await interaction.response.send_message("❌ Bitte zuerst ein Modul auswählen.", ephemeral=True)
            return
        enabled = self.values[0] == "on"
        key = f"module.{self.config_view.selected_module}.enabled"
        self.config_view.cog.store.set(key, enabled)
        await interaction.response.edit_message(embed=self.config_view.build_embed(saved=f"✅ `{key}` = `{enabled}` gespeichert."), view=self.config_view)


class SettingsModuleConfigView(discord.ui.View):
    def __init__(self, cog: "SettingsCog"):
        super().__init__(timeout=300)
        self.cog = cog
        self.selected_module: str | None = None
        self.add_item(SettingsModuleNameSelect(self))
        self.add_item(SettingsModuleStatusSelect(self))

    def build_embed(self, saved: str | None = None) -> discord.Embed:
        selected = self.selected_module or "noch nicht ausgewählt"
        embed = discord.Embed(
            title="🧩 Modul schalten",
            description="Wähle zuerst das Modul und danach Aktivieren/Deaktivieren.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Ausgewähltes Modul", value=f"`{selected}`", inline=False)
        embed.add_field(name="Hinweis", value="Cogs und Slash-Commands werden erst nach Container-Neustart wirklich geladen oder entfernt.", inline=False)
        if saved:
            embed.add_field(name="Gespeichert", value=saved, inline=False)
        return embed


class SettingsChannelKeySelect(discord.ui.Select):
    def __init__(self, view: "SettingsChannelConfigView"):
        self.config_view = view
        options = [
            discord.SelectOption(label=label, value=key, emoji=emoji)
            for key, label, emoji in CHANNEL_SETTING_OPTIONS
        ]
        super().__init__(placeholder="Welche Channel-Einstellung ändern?", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.config_view.selected_key = self.values[0]
        await interaction.response.edit_message(embed=self.config_view.build_embed(interaction), view=self.config_view)


class SettingsChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, view: "SettingsChannelConfigView"):
        super().__init__(
            placeholder="Discord-Channel auswählen ...",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        )
        self.config_view = view

    async def callback(self, interaction: discord.Interaction):
        if not self.config_view.selected_key:
            await interaction.response.send_message("❌ Bitte zuerst auswählen, welche Channel-Einstellung geändert werden soll.", ephemeral=True)
            return
        raw_channel = self.values[0]
        channel_id = int(raw_channel.id)
        channel = interaction.guild.get_channel(channel_id) if interaction.guild else None
        if channel is None and interaction.guild is not None:
            try:
                channel = await interaction.guild.fetch_channel(channel_id)
            except discord.HTTPException:
                channel = None
        if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)) and getattr(channel, "type", None) != discord.ChannelType.news:
            await interaction.response.send_message("❌ Bitte einen Text- oder Ankündigungskanal auswählen.", ephemeral=True)
            return
        self.config_view.cog.store.set(self.config_view.selected_key, channel_id)
        await interaction.response.edit_message(
            embed=self.config_view.build_embed(interaction, saved=f"✅ `{self.config_view.selected_key}` → {channel.mention} gespeichert."),
            view=self.config_view,
        )


class SettingsChannelConfigView(discord.ui.View):
    def __init__(self, cog: "SettingsCog"):
        super().__init__(timeout=300)
        self.cog = cog
        self.selected_key: str | None = None
        self.add_item(SettingsChannelKeySelect(self))
        self.add_item(SettingsChannelPicker(self))

    def build_embed(self, interaction: discord.Interaction, saved: str | None = None) -> discord.Embed:
        selected = self.selected_key or "noch nicht ausgewählt"
        embed = discord.Embed(
            title="#️⃣ Channel setzen",
            description="Wähle zuerst die Einstellung und danach direkt den Discord-Channel. Keine Channel-ID nötig.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Ausgewählte Einstellung", value=f"`{selected}`", inline=False)
        if saved:
            embed.add_field(name="Gespeichert", value=saved, inline=False)
        return embed


class SettingsRoleKeySelect(discord.ui.Select):
    def __init__(self, view: "SettingsRoleConfigView"):
        self.config_view = view
        options = [
            discord.SelectOption(label=label, value=key, emoji=emoji)
            for key, label, emoji in ROLE_SETTING_OPTIONS
        ]
        super().__init__(placeholder="Welche Rollen-Einstellung ändern?", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        self.config_view.selected_key = self.values[0]
        await interaction.response.edit_message(embed=self.config_view.build_embed(interaction), view=self.config_view)


class SettingsRolePicker(discord.ui.RoleSelect):
    def __init__(self, view: "SettingsRoleConfigView"):
        super().__init__(placeholder="Discord-Rolle auswählen ...", min_values=1, max_values=1)
        self.config_view = view

    async def callback(self, interaction: discord.Interaction):
        if not self.config_view.selected_key:
            await interaction.response.send_message("❌ Bitte zuerst auswählen, welche Rollen-Einstellung geändert werden soll.", ephemeral=True)
            return
        role = self.values[0]
        self.config_view.cog.store.set(self.config_view.selected_key, int(role.id))
        await interaction.response.edit_message(
            embed=self.config_view.build_embed(interaction, saved=f"✅ `{self.config_view.selected_key}` → {role.mention} gespeichert."),
            view=self.config_view,
        )


class SettingsRoleConfigView(discord.ui.View):
    def __init__(self, cog: "SettingsCog"):
        super().__init__(timeout=300)
        self.cog = cog
        self.selected_key: str | None = None
        self.add_item(SettingsRoleKeySelect(self))
        self.add_item(SettingsRolePicker(self))

    def build_embed(self, interaction: discord.Interaction, saved: str | None = None) -> discord.Embed:
        selected = self.selected_key or "noch nicht ausgewählt"
        embed = discord.Embed(
            title="👥 Rolle setzen",
            description="Wähle zuerst die Einstellung und danach direkt die Discord-Rolle. Keine Rollen-ID nötig.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Ausgewählte Einstellung", value=f"`{selected}`", inline=False)
        if saved:
            embed.add_field(name="Gespeichert", value=saved, inline=False)
        return embed


class SettingsModuleModal(discord.ui.Modal, title="Modul schalten"):
    name = discord.ui.TextInput(label="Modulname", placeholder="translator, autoclear, audit ...", max_length=80)
    status = discord.ui.TextInput(label="Status", placeholder="on/off oder an/aus", max_length=20)

    def __init__(self, cog: "SettingsCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        raw_status = str(self.status.value).strip().lower()
        enabled = raw_status in {"on", "an", "aktiv", "true", "1", "ja", "yes"}
        disabled = raw_status in {"off", "aus", "inaktiv", "false", "0", "nein", "no"}
        if not enabled and not disabled:
            await interaction.response.send_message("❌ Status muss `on`/`off` oder `an`/`aus` sein.", ephemeral=True)
            return
        module_name = str(self.name.value).strip().lower()
        self.cog.store.set(f"module.{module_name}.enabled", enabled)
        await interaction.response.send_message(
            f"✅ Gespeichert: `module.{module_name}.enabled = {enabled}`\n"
            "Hinweis: Laden/Entladen von Cogs und Slash-Commands greift erst nach Container-Neustart.",
            ephemeral=True,
        )


class SettingsChannelModal(discord.ui.Modal, title="Channel setzen"):
    key = discord.ui.TextInput(label="Key", placeholder="welcome, rules, memberlog, autoclear, translator_target", max_length=80)
    channel_id = discord.ui.TextInput(label="Channel-ID", placeholder="z. B. 1504595234020004034", max_length=32)

    def __init__(self, cog: "SettingsCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        clean_key = str(self.key.value).strip().lower()
        if not clean_key.startswith("channel."):
            clean_key = f"channel.{clean_key}"
        try:
            channel_id = int(str(self.channel_id.value).strip())
        except ValueError:
            await interaction.response.send_message("❌ Channel-ID muss eine Zahl sein.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(channel_id) if interaction.guild else None
        self.cog.store.set(clean_key, channel_id)
        await interaction.response.send_message(
            f"✅ Gespeichert: `{clean_key}` → {channel.mention if channel else f'`{channel_id}`'}",
            ephemeral=True,
        )


class SettingsRoleModal(discord.ui.Modal, title="Rolle setzen"):
    key = discord.ui.TextInput(label="Key", placeholder="guest, arc_raider ...", max_length=80)
    role_id = discord.ui.TextInput(label="Rollen-ID", placeholder="z. B. 1504591643205173441", max_length=32)

    def __init__(self, cog: "SettingsCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        clean_key = str(self.key.value).strip().lower()
        if not clean_key.startswith("role."):
            clean_key = f"role.{clean_key}"
        try:
            role_id = int(str(self.role_id.value).strip())
        except ValueError:
            await interaction.response.send_message("❌ Rollen-ID muss eine Zahl sein.", ephemeral=True)
            return
        role = interaction.guild.get_role(role_id) if interaction.guild else None
        self.cog.store.set(clean_key, role_id)
        await interaction.response.send_message(
            f"✅ Gespeichert: `{clean_key}` → {role.mention if role else f'`{role_id}`'}",
            ephemeral=True,
        )


class SettingsValueModal(discord.ui.Modal, title="Einzelwert setzen"):
    key = discord.ui.TextInput(label="Key", placeholder="autoclear.scan_limit", max_length=120)
    value = discord.ui.TextInput(label="Wert", placeholder="z. B. 100", max_length=500)

    def __init__(self, cog: "SettingsCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        key = str(self.key.value).strip()
        if key not in ALLOWED_VALUE_KEYS:
            allowed = "\n".join(f"- `{k}`" for k in sorted(ALLOWED_VALUE_KEYS))
            await interaction.response.send_message(f"❌ Dieser Key ist nicht freigegeben. Erlaubt:\n{allowed}", ephemeral=True)
            return
        try:
            parsed = self.cog.parse_value(key, str(self.value.value))
        except Exception as error:
            await interaction.response.send_message(f"❌ Ungültiger Wert: `{error}`", ephemeral=True)
            return
        self.cog.store.set(key, parsed)
        await interaction.response.send_message(f"✅ Gespeichert: `{key} = {parsed}`", ephemeral=True)


class SettingsPanelSelect(discord.ui.Select):
    def __init__(self, cog: "SettingsCog"):
        self.cog = cog
        options = [
            discord.SelectOption(label="Modul schalten", value="module", emoji="🧩", description="Cog grundsätzlich aktivieren/deaktivieren"),
        ]
        super().__init__(placeholder="Allgemeine Bot-Aktion auswählen ...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        if value == "module":
            view = SettingsModuleConfigView(self.cog)
            await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)


class SettingsPanelView(discord.ui.View):
    def __init__(self, cog: "SettingsCog"):
        super().__init__(timeout=300)
        self.cog = cog
        self.add_item(SettingsPanelSelect(cog))

    @discord.ui.button(label="Aktualisieren", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.cog.build_settings_embed(interaction), view=self)

    @discord.ui.button(label="Export", emoji="📤", style=discord.ButtonStyle.primary)
    async def export(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_export(interaction)


class SettingsCog(commands.Cog):
    settings_group = app_commands.Group(name="settings", description="Bot-Einstellungen direkt im Discord verwalten")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def store(self):
        return self.bot.settings

    def icon(self, value: Any) -> str:
        return "✅" if bool(value) else "❌"

    def parse_value(self, key: str, value: str) -> Any:
        value_type = ALLOWED_VALUE_KEYS.get(key, str)
        if value_type is bool:
            normalized = value.strip().lower()
            if normalized in {"true", "1", "ja", "yes", "on", "an"}:
                return True
            if normalized in {"false", "0", "nein", "no", "off", "aus"}:
                return False
            raise ValueError("Bool-Wert muss true/false sein.")
        if value_type is int:
            return int(value)
        if key == "autoclear.schedule_times":
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def build_settings_embed(self, interaction: discord.Interaction) -> discord.Embed:
        settings = self.store.all()
        modules = {k: v for k, v in settings.items() if k.startswith("module.") and k.endswith(".enabled")}
        module_lines = []
        for key, value in sorted(modules.items()):
            name = key.removeprefix("module.").removesuffix(".enabled")
            module_lines.append(f"{self.icon(value)} `{name}`")

        embed = discord.Embed(
            title="⚙️ Settings-Panel",
            description=(
                "Dieses Panel ist nur noch für **allgemeine Bot-Verwaltung** zuständig.\n"
                "Channel, Rollen, Texte und Funktionsoptionen stellst du direkt im passenden Fach-Panel ein."
            ),
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Module", value="\n".join(module_lines) or "Keine Module gespeichert", inline=False)
        embed.add_field(
            name="Wo stelle ich was ein?",
            value=(
                "🌍 `/translate panel` → Quellkanäle, Zielkanal, Provider, Webhooks\n"
                "👋 `/welcome panel` → Welcome-/Leave-Channel und Texte\n"
                "📜 `/rules panel` → Hausordnung-Channel, Gast-Rolle, Text\n"
                "🧾 `/memberlog panel` → Log-Channel, Rollen, Cleanup\n"
                "🧹 `/autoclear panel` → AutoClear-Channel, Ziel-Bot, Regeln, Zeitplan\n"
                "🧨 `/channel-clear panel` → Kanäle manuell leeren"
            ),
            inline=False,
        )
        embed.add_field(
            name="Config-Regel",
            value="`.env` = Tokens/API-Keys · `config/main.yaml` = Start/Module · `data/settings.sqlite` = Discord-Einstellungen",
            inline=False,
        )
        embed.add_field(name="Logs", value="`logs/bot.log` und `logs/error.log`", inline=False)
        return embed

    async def send_export(self, interaction: discord.Interaction):
        data = self.store.all()
        path = "data/settings_export.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if interaction.response.is_done():
            await interaction.followup.send("✅ Settings exportiert.", file=discord.File(path), ephemeral=True)
        else:
            await interaction.response.send_message("✅ Settings exportiert.", file=discord.File(path), ephemeral=True)

    @settings_group.command(name="panel", description="Öffnet das Settings-Bedienfeld.")
    @admin_only()
    async def panel(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self.build_settings_embed(interaction), view=SettingsPanelView(self), ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        handled = await handle_app_command_error(interaction, error)
        if handled:
            return
        logging.exception("Settings-Command Fehler: %s", error)
        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(SettingsCog(bot))
