from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands, tasks
from utils.permissions import admin_only, handle_app_command_error


class AutoClearCog(commands.Cog):
    autoclear_group = app_commands.Group(name="autoclear", description="AutoClear verwalten und ausführen")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_interval_run: datetime | None = None
        self.autoclear_loop.start()

    def cog_unload(self):
        self.autoclear_loop.cancel()

    @property
    def store(self):
        return self.bot.settings

    def get_config(self) -> dict[str, Any]:
        cfg = self.bot.config_data.get("autoclear", {})
        return {
            "enabled": self.store.get("autoclear.enabled", cfg.get("enabled", False)),
            "channel_id": self.store.get("channel.autoclear", cfg.get("channel_id", 0)),
            "target_bot_user_id": self.store.get("autoclear.target_bot_user_id", cfg.get("target_bot_user_id", 0)),
            "schedule_mode": self.store.get("autoclear.schedule_mode", cfg.get("schedule", {}).get("mode", "interval")),
            "schedule_times": self.store.get("autoclear.schedule_times", cfg.get("schedule", {}).get("times", [])),
            "timezone": self.store.get("autoclear.timezone", cfg.get("schedule", {}).get("timezone", "Europe/Berlin")),
            "interval_minutes": self.store.get("autoclear.interval_minutes", cfg.get("interval_minutes", 30)),
            "delete_after_minutes": self.store.get("autoclear.delete_after_minutes", cfg.get("delete_after_minutes", 120)),
            "scan_limit": self.store.get("autoclear.scan_limit", cfg.get("scan_limit", 100)),
            "dry_run": self.store.get("autoclear.dry_run", cfg.get("dry_run", True)),
            "delete_rules": {
                "required_contains": self.store.get(
                    "autoclear.delete_required_contains",
                    cfg.get("delete_rules", {}).get("required_contains", []),
                )
            },
            "keep_rules": {
                "contains": self.store.get(
                    "autoclear.keep_contains",
                    cfg.get("keep_rules", {}).get("contains", []),
                )
            },
        }

    def get_logging_config(self) -> dict:
        return self.bot.config_data.get("logging", {})

    def log_kept_messages(self) -> bool:
        return bool(self.get_logging_config().get("log_kept_messages", False))

    def log_dry_run_matches(self) -> bool:
        return bool(self.get_logging_config().get("log_dry_run_matches", False))

    def extract_message_text(self, message: discord.Message) -> str:
        parts = []
        if message.content:
            parts.append(message.content)
        for embed in message.embeds:
            if embed.title:
                parts.append(embed.title)
            if embed.description:
                parts.append(embed.description)
            if embed.url:
                parts.append(embed.url)
            if embed.author and embed.author.name:
                parts.append(embed.author.name)
            if embed.footer and embed.footer.text:
                parts.append(embed.footer.text)
            for field in embed.fields:
                if field.name:
                    parts.append(field.name)
                if field.value:
                    parts.append(field.value)
        return "\n".join(parts)

    def is_old_enough(self, message: discord.Message, delete_after_minutes: int) -> bool:
        now = datetime.now(timezone.utc)
        return now - message.created_at >= timedelta(minutes=delete_after_minutes)

    def should_delete_message(self, message: discord.Message, config: dict) -> tuple[bool, str]:
        target_bot_user_id = int(config.get("target_bot_user_id", 0) or 0)
        delete_after_minutes = int(config.get("delete_after_minutes", 120) or 120)

        if target_bot_user_id and message.author.id != target_bot_user_id:
            return False, "Autor ist nicht der konfigurierte Ziel-Bot."

        if not self.is_old_enough(message, delete_after_minutes):
            return False, "Nachricht ist noch nicht alt genug."

        text_lower = self.extract_message_text(message).lower()

        keep_words = config.get("keep_rules", {}).get("contains", []) or []
        for word in keep_words:
            if str(word).lower() in text_lower:
                return False, f"Schutzbegriff gefunden: {word}"

        required_words = config.get("delete_rules", {}).get("required_contains", []) or []
        for word in required_words:
            if str(word).lower() not in text_lower:
                return False, f"Pflichtbegriff fehlt: {word}"

        if not required_words:
            return False, "Keine Löschregel gesetzt."

        return True, "AutoClear-Regel erfüllt."

    async def scan_and_clear(self, dry_run_override: bool | None = None):
        config = self.get_config()
        if not config.get("enabled", False):
            return {"enabled": False, "checked": 0, "deleted": 0, "would_delete": 0, "kept": 0, "errors": 0}

        channel_id = int(config.get("channel_id", 0) or 0)
        scan_limit = int(config.get("scan_limit", 100) or 100)
        dry_run = bool(config.get("dry_run", True)) if dry_run_override is None else dry_run_override

        channel = self.bot.get_channel(channel_id)
        if not channel:
            logging.warning("Autoclear-Channel nicht gefunden: %s", channel_id)
            return {"enabled": True, "checked": 0, "deleted": 0, "would_delete": 0, "kept": 0, "errors": 1, "dry_run": dry_run}

        checked = deleted = would_delete = kept = errors = 0
        async for message in channel.history(limit=scan_limit):
            checked += 1
            should_delete, reason = self.should_delete_message(message, config)
            if not should_delete:
                kept += 1
                if self.log_kept_messages():
                    logging.info("Autoclear behalten | Message-ID: %s | Grund: %s", message.id, reason)
                continue
            if dry_run:
                would_delete += 1
                if self.log_dry_run_matches():
                    logging.info("Autoclear DRY-RUN würde löschen | Message-ID: %s | Grund: %s", message.id, reason)
                continue
            try:
                await message.delete()
                deleted += 1
                logging.info("Autoclear gelöscht | Message-ID: %s | Grund: %s", message.id, reason)
            except discord.Forbidden:
                errors += 1
                logging.error("Autoclear: Keine Rechte zum Löschen von Message-ID: %s", message.id)
            except discord.HTTPException as error:
                errors += 1
                logging.error("Autoclear: HTTP-Fehler bei Message-ID %s: %s", message.id, error)

        return {"enabled": True, "checked": checked, "deleted": deleted, "would_delete": would_delete, "kept": kept, "errors": errors, "dry_run": dry_run}

    def _get_timezone(self, timezone_name: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone_name or "Europe/Berlin")
        except ZoneInfoNotFoundError:
            logging.warning("AutoClear: Ungültige Zeitzone '%s', nutze Europe/Berlin.", timezone_name)
            return ZoneInfo("Europe/Berlin")

    def _normalize_schedule_times(self, raw_times: Any) -> list[str]:
        if isinstance(raw_times, str):
            raw_times = [item.strip() for item in raw_times.split(",") if item.strip()]
        if not isinstance(raw_times, list):
            return []

        result: list[str] = []
        for item in raw_times:
            text = str(item).strip()
            try:
                parts = text.split(":")
                if len(parts) != 2:
                    continue
                hour = int(parts[0])
                minute = int(parts[1])
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    result.append(f"{hour:02d}:{minute:02d}")
            except ValueError:
                continue
        return sorted(set(result))

    def _should_run_now(self, config: dict[str, Any]) -> bool:
        mode = str(config.get("schedule_mode", "interval") or "interval").lower().strip()
        now_utc = datetime.now(timezone.utc)

        if mode == "daily":
            tz = self._get_timezone(str(config.get("timezone", "Europe/Berlin") or "Europe/Berlin"))
            now_local = now_utc.astimezone(tz)
            current_time = now_local.strftime("%H:%M")
            times = self._normalize_schedule_times(config.get("schedule_times", []))
            if not times:
                return False
            if current_time not in times:
                return False

            slot = f"{now_local.strftime('%Y-%m-%d')} {current_time}"
            last_slot = self.store.get("autoclear.last_daily_slot", "")
            if last_slot == slot:
                return False
            self.store.set("autoclear.last_daily_slot", slot)
            return True

        interval_minutes = max(1, int(config.get("interval_minutes", 30) or 30))
        if self._last_interval_run is None:
            self._last_interval_run = now_utc
            return True
        if now_utc - self._last_interval_run >= timedelta(minutes=interval_minutes):
            self._last_interval_run = now_utc
            return True
        return False

    @tasks.loop(minutes=1)
    async def autoclear_loop(self):
        config = self.get_config()
        if not config.get("enabled", False):
            return
        if not self._should_run_now(config):
            return
        result = await self.scan_and_clear()
        logging.info("Autoclear automatisch ausgeführt: %s", result)

    @autoclear_loop.before_loop
    async def before_autoclear_loop(self):
        await self.bot.wait_until_ready()

    def _format_rules(self, rules: list[str]) -> str:
        return "\n".join(f"- {r}" for r in rules) if rules else "- keine"

    def build_status_embed(self, guild: discord.Guild | None = None, title: str = "🧹 AutoClear Panel") -> discord.Embed:
        cfg = self.get_config()
        channel = guild.get_channel(int(cfg.get("channel_id", 0) or 0)) if guild else None
        color = discord.Color.green() if cfg.get("enabled") else discord.Color.red()
        embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
        mode = str(cfg.get("schedule_mode", "interval") or "interval")
        times = ", ".join(self._normalize_schedule_times(cfg.get("schedule_times", []))) or "-"
        dry_run_text = "✅ Aktiv – es wird nichts gelöscht" if cfg.get("dry_run") else "❌ Aus – AutoClear löscht wirklich"
        if mode == "daily":
            plan = f"täglich um `{times}` (`{cfg.get('timezone', 'Europe/Berlin')}`)"
        else:
            plan = f"alle `{cfg.get('interval_minutes')} Minuten`"
        embed.description = (
            f"**Status:** {'✅ Aktiv' if cfg.get('enabled') else '❌ Deaktiviert'}\n"
            f"**Dry-Run:** {dry_run_text}\n"
            f"**Channel:** {channel.mention if channel else f'`{cfg.get("channel_id", 0)}`'}\n"
            f"**Ziel-Bot-ID:** `{cfg.get('target_bot_user_id', 0)}`\n"
            f"**Zeitplan:** {plan}\n"
            f"**Löschen nach:** `{cfg.get('delete_after_minutes')} Minuten`\n"
            f"**Scan-Limit:** `{cfg.get('scan_limit')}`"
        )
        embed.add_field(name="Löschregeln", value=self._format_rules(cfg.get("delete_rules", {}).get("required_contains", []))[:1024], inline=False)
        embed.add_field(name="Schutzbegriffe", value=self._format_rules(cfg.get("keep_rules", {}).get("contains", []))[:1024], inline=False)
        embed.set_footer(text="Bedienung über /autoclear panel. Einzelbefehle sind ausgeblendet.")
        return embed

    async def send_panel(self, interaction: discord.Interaction):
        embed = self.build_status_embed(interaction.guild)
        await interaction.followup.send(embed=embed, view=AutoClearPanelView(self, interaction.user.id), ephemeral=True)

    @autoclear_group.command(name="panel", description="Öffnet das AutoClear-Bedienfeld mit Buttons und Dropdown.")
    @admin_only()
    async def panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.send_panel(interaction)

    # ausgeblendet: @autoclear_group.command(name="status", description="Zeigt die aktuelle AutoClear-Konfiguration.")
    @admin_only()
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=self.build_status_embed(interaction.guild, title="🧹 AutoClear Status"), ephemeral=True)

    # ausgeblendet: @autoclear_group.command(name="setup", description="Richtet AutoClear für einen Channel und Ziel-Bot ein.")
    @admin_only()
    async def setup_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel, target_bot: discord.User, delete_after_minutes: int = 120, scan_limit: int = 100):
        await interaction.response.defer(ephemeral=True)
        self.store.set("channel.autoclear", channel.id)
        self.store.set("autoclear.target_bot_user_id", target_bot.id)
        self.store.set("autoclear.delete_after_minutes", delete_after_minutes)
        self.store.set("autoclear.scan_limit", scan_limit)
        await interaction.followup.send(f"✅ AutoClear eingerichtet: {channel.mention}, Ziel-Bot `{target_bot}`.", ephemeral=True)

    # ausgeblendet: @autoclear_group.command(name="enable", description="Aktiviert AutoClear.")
    @admin_only()
    async def enable(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.store.set("autoclear.enabled", True)
        await interaction.followup.send("✅ AutoClear aktiviert.", ephemeral=True)

    # ausgeblendet: @autoclear_group.command(name="disable", description="Deaktiviert AutoClear.")
    @admin_only()
    async def disable(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.store.set("autoclear.enabled", False)
        await interaction.followup.send("✅ AutoClear deaktiviert.", ephemeral=True)

    # ausgeblendet: @autoclear_group.command(name="dryrun", description="Schaltet Dry-Run per Auswahl an/aus.")
    @app_commands.describe(status="Dry-Run aktivieren oder deaktivieren")
    @app_commands.choices(status=[
        app_commands.Choice(name="Aktivieren - nur testen, nichts löschen", value="on"),
        app_commands.Choice(name="Deaktivieren - wirklich löschen", value="off"),
    ])
    @admin_only()
    async def dryrun(self, interaction: discord.Interaction, status: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        enabled = status.value == "on"
        self.store.set("autoclear.dry_run", enabled)
        label = "aktiviert - es wird nichts gelöscht" if enabled else "deaktiviert - AutoClear darf wirklich löschen"
        await interaction.followup.send(f"✅ AutoClear Dry-Run: `{label}`", ephemeral=True)

    # ausgeblendet: @autoclear_group.command(name="schedule", description="Stellt ein, wann AutoClear automatisch laufen soll.")
    @app_commands.describe(
        mode="Intervall oder täglich feste Uhrzeit",
        time="Uhrzeit bei daily, z. B. 04:00. Mehrere mit Komma: 04:00,18:30",
        interval_minutes="Intervall bei interval, z. B. 30",
        timezone_name="Zeitzone, Standard: Europe/Berlin",
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="Intervall - alle X Minuten", value="interval"),
        app_commands.Choice(name="Täglich - feste Uhrzeit", value="daily"),
    ])
    @admin_only()
    async def schedule(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
        time: str | None = None,
        interval_minutes: int | None = None,
        timezone_name: str = "Europe/Berlin",
    ):
        await interaction.response.defer(ephemeral=True)
        selected_mode = mode.value

        if selected_mode == "daily":
            times = self._normalize_schedule_times(time or "")
            if not times:
                await interaction.followup.send("❌ Bitte eine gültige Uhrzeit angeben, z. B. `04:00` oder `04:00,18:30`.", ephemeral=True)
                return
            # Validiert die Zeitzone frühzeitig.
            self._get_timezone(timezone_name)
            self.store.set("autoclear.schedule_mode", "daily")
            self.store.set("autoclear.schedule_times", times)
            self.store.set("autoclear.timezone", timezone_name)
            await interaction.followup.send(
                f"✅ AutoClear läuft jetzt täglich um `{', '.join(times)}` (`{timezone_name}`).",
                ephemeral=True,
            )
            return

        minutes = int(interval_minutes or self.store.get("autoclear.interval_minutes", 30) or 30)
        if minutes < 1:
            await interaction.followup.send("❌ Das Intervall muss mindestens 1 Minute sein.", ephemeral=True)
            return
        self.store.set("autoclear.schedule_mode", "interval")
        self.store.set("autoclear.interval_minutes", minutes)
        self._last_interval_run = None
        await interaction.followup.send(f"✅ AutoClear läuft jetzt alle `{minutes}` Minuten.", ephemeral=True)

    # ausgeblendet: @autoclear_group.command(name="time-add", description="Fügt eine tägliche AutoClear-Uhrzeit hinzu.")
    @admin_only()
    async def time_add(self, interaction: discord.Interaction, time: str):
        await interaction.response.defer(ephemeral=True)
        new_times = self._normalize_schedule_times(time)
        if not new_times:
            await interaction.followup.send("❌ Ungültige Uhrzeit. Beispiel: `04:00`", ephemeral=True)
            return
        current = self._normalize_schedule_times(self.store.get("autoclear.schedule_times", []))
        merged = sorted(set(current + new_times))
        self.store.set("autoclear.schedule_mode", "daily")
        self.store.set("autoclear.schedule_times", merged)
        await interaction.followup.send(f"✅ AutoClear-Uhrzeiten: `{', '.join(merged)}`", ephemeral=True)

    # ausgeblendet: @autoclear_group.command(name="time-remove", description="Entfernt eine tägliche AutoClear-Uhrzeit.")
    @admin_only()
    async def time_remove(self, interaction: discord.Interaction, time: str):
        await interaction.response.defer(ephemeral=True)
        remove_times = set(self._normalize_schedule_times(time))
        if not remove_times:
            await interaction.followup.send("❌ Ungültige Uhrzeit. Beispiel: `04:00`", ephemeral=True)
            return
        current = self._normalize_schedule_times(self.store.get("autoclear.schedule_times", []))
        remaining = [item for item in current if item not in remove_times]
        self.store.set("autoclear.schedule_times", remaining)
        await interaction.followup.send(f"✅ AutoClear-Uhrzeiten: `{', '.join(remaining) or '-'}`", ephemeral=True)

    def _list_add(self, key: str, text: str) -> list[str]:
        items = self.store.get(key, []) or []
        if text not in items:
            items.append(text)
            self.store.set(key, items)
        return items

    def _list_remove(self, key: str, text: str) -> list[str]:
        items = self.store.get(key, []) or []
        items = [item for item in items if item != text]
        self.store.set(key, items)
        return items

    # ausgeblendet: @autoclear_group.command(name="rule-add", description="Fügt einen Pflichtbegriff zum Löschen hinzu.")
    @admin_only()
    async def rule_add(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer(ephemeral=True)
        items = self._list_add("autoclear.delete_required_contains", text)
        await interaction.followup.send(f"✅ Löschregel hinzugefügt: `{text}`\nAktuell: `{len(items)}` Regeln", ephemeral=True)

    # ausgeblendet: @autoclear_group.command(name="rule-remove", description="Entfernt einen Pflichtbegriff zum Löschen.")
    @admin_only()
    async def rule_remove(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer(ephemeral=True)
        items = self._list_remove("autoclear.delete_required_contains", text)
        await interaction.followup.send(f"✅ Löschregel entfernt: `{text}`\nAktuell: `{len(items)}` Regeln", ephemeral=True)

    # ausgeblendet: @autoclear_group.command(name="keep-add", description="Fügt einen Schutzbegriff hinzu.")
    @admin_only()
    async def keep_add(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer(ephemeral=True)
        items = self._list_add("autoclear.keep_contains", text)
        await interaction.followup.send(f"✅ Schutzbegriff hinzugefügt: `{text}`\nAktuell: `{len(items)}` Begriffe", ephemeral=True)

    # ausgeblendet: @autoclear_group.command(name="keep-remove", description="Entfernt einen Schutzbegriff.")
    @admin_only()
    async def keep_remove(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer(ephemeral=True)
        items = self._list_remove("autoclear.keep_contains", text)
        await interaction.followup.send(f"✅ Schutzbegriff entfernt: `{text}`\nAktuell: `{len(items)}` Begriffe", ephemeral=True)

    # ausgeblendet: @autoclear_group.command(name="run", description="Führt AutoClear jetzt aus.")
    @admin_only()
    async def run(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        result = await self.scan_and_clear()
        await interaction.followup.send(
            "**AutoClear ausgeführt.**\n"
            f"Dry-Run: `{result.get('dry_run', True)}`\n"
            f"Geprüft: `{result['checked']}`\n"
            f"Gelöscht: `{result['deleted']}`\n"
            f"Würde löschen: `{result['would_delete']}`\n"
            f"Behalten/Ignoriert: `{result['kept']}`\n"
            f"Fehler: `{result['errors']}`",
            ephemeral=True,
        )

    # ausgeblendet: @autoclear_group.command(name="test", description="Prüft, was gelöscht würde, löscht aber nichts.")
    @admin_only()
    async def test(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        result = await self.scan_and_clear(dry_run_override=True)
        await interaction.followup.send(
            "**AutoClear-Test abgeschlossen.**\n"
            f"Geprüft: `{result['checked']}`\n"
            f"Würde löschen: `{result['would_delete']}`\n"
            f"Behalten/Ignoriert: `{result['kept']}`\n"
            f"Fehler: `{result['errors']}`",
            ephemeral=True,
        )

    # ausgeblendet: @autoclear_group.command(name="now", description="Alias für /autoclear run.")
    @admin_only()
    async def now(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        result = await self.scan_and_clear()
        await interaction.followup.send(
            "**AutoClear ausgeführt.**\n"
            f"Dry-Run: `{result.get('dry_run', True)}`\n"
            f"Geprüft: `{result['checked']}`\n"
            f"Gelöscht: `{result['deleted']}`\n"
            f"Würde löschen: `{result['would_delete']}`\n"
            f"Behalten/Ignoriert: `{result['kept']}`\n"
            f"Fehler: `{result['errors']}`",
            ephemeral=True,
        )

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        handled = await handle_app_command_error(interaction, error)
        if handled:
            return
        logging.exception("AutoClear-Command Fehler: %s", error)
        raise error


class AutoClearPanelView(discord.ui.View):
    def __init__(self, cog: AutoClearCog, owner_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id
        self.add_item(AutoClearActionSelect(cog, owner_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("⛔ Dieses Panel gehört nicht dir. Öffne dein eigenes mit `/autoclear panel`.", ephemeral=True)
            return False
        return True

    async def refresh_panel(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.cog.build_status_embed(interaction.guild), view=self)

    @discord.ui.button(label="Aktiv umschalten", emoji="✅", style=discord.ButtonStyle.success, row=0)
    async def toggle_enabled(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = self.cog.get_config()
        new_value = not bool(cfg.get("enabled"))
        self.cog.store.set("autoclear.enabled", new_value)
        await self.refresh_panel(interaction)

    @discord.ui.button(label="Dry-Run umschalten", emoji="🧪", style=discord.ButtonStyle.primary, row=0)
    async def toggle_dryrun(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = self.cog.get_config()
        new_value = not bool(cfg.get("dry_run"))
        self.cog.store.set("autoclear.dry_run", new_value)
        await self.refresh_panel(interaction)

    @discord.ui.button(label="Testlauf", emoji="▶️", style=discord.ButtonStyle.secondary, row=0)
    async def run_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        result = await self.cog.scan_and_clear(dry_run_override=True)
        await interaction.followup.send(
            "**AutoClear-Test abgeschlossen.**\n"
            f"Geprüft: `{result['checked']}`\n"
            f"Würde löschen: `{result['would_delete']}`\n"
            f"Behalten/Ignoriert: `{result['kept']}`\n"
            f"Fehler: `{result['errors']}`",
            ephemeral=True,
        )

    @discord.ui.button(label="Jetzt ausführen", emoji="🗑️", style=discord.ButtonStyle.danger, row=0)
    async def run_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        result = await self.cog.scan_and_clear()
        await interaction.followup.send(
            "**AutoClear ausgeführt.**\n"
            f"Dry-Run: `{result.get('dry_run', True)}`\n"
            f"Geprüft: `{result['checked']}`\n"
            f"Gelöscht: `{result['deleted']}`\n"
            f"Würde löschen: `{result['would_delete']}`\n"
            f"Behalten/Ignoriert: `{result['kept']}`\n"
            f"Fehler: `{result['errors']}`",
            ephemeral=True,
        )

    @discord.ui.button(label="Aktualisieren", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.refresh_panel(interaction)


class AutoClearActionSelect(discord.ui.Select):
    def __init__(self, cog: AutoClearCog, owner_id: int):
        self.cog = cog
        self.owner_id = owner_id
        options = [
            discord.SelectOption(label="Setup ändern", value="setup", description="Channel-ID, Ziel-Bot-ID, Alter und Scan-Limit setzen", emoji="⚙️"),
            discord.SelectOption(label="Zeitplan: Intervall", value="schedule_interval", description="AutoClear alle X Minuten laufen lassen", emoji="⏱️"),
            discord.SelectOption(label="Zeitplan: täglich", value="schedule_daily", description="AutoClear täglich zu einer oder mehreren Uhrzeiten", emoji="⏰"),
            discord.SelectOption(label="Löschregel hinzufügen", value="rule_add", description="Pflichtbegriff ergänzen", emoji="➕"),
            discord.SelectOption(label="Löschregel entfernen", value="rule_remove", description="Pflichtbegriff entfernen", emoji="➖"),
            discord.SelectOption(label="Schutzbegriff hinzufügen", value="keep_add", description="Nachrichten mit diesem Text behalten", emoji="🛡️"),
            discord.SelectOption(label="Schutzbegriff entfernen", value="keep_remove", description="Schutzbegriff entfernen", emoji="🧹"),
        ]
        super().__init__(placeholder="Aktion auswählen …", min_values=1, max_values=1, options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        if value == "setup":
            await interaction.response.send_modal(AutoClearSetupModal(self.cog))
        elif value == "schedule_interval":
            await interaction.response.send_modal(AutoClearIntervalModal(self.cog))
        elif value == "schedule_daily":
            await interaction.response.send_modal(AutoClearDailyModal(self.cog))
        elif value == "rule_add":
            await interaction.response.send_modal(AutoClearListModal(self.cog, "autoclear.delete_required_contains", "Löschregel hinzufügen", "hinzugefügt"))
        elif value == "rule_remove":
            await interaction.response.send_modal(AutoClearListModal(self.cog, "autoclear.delete_required_contains", "Löschregel entfernen", "entfernt", remove=True))
        elif value == "keep_add":
            await interaction.response.send_modal(AutoClearListModal(self.cog, "autoclear.keep_contains", "Schutzbegriff hinzufügen", "hinzugefügt"))
        elif value == "keep_remove":
            await interaction.response.send_modal(AutoClearListModal(self.cog, "autoclear.keep_contains", "Schutzbegriff entfernen", "entfernt", remove=True))


class AutoClearSetupModal(discord.ui.Modal, title="AutoClear Setup ändern"):
    def __init__(self, cog: AutoClearCog):
        super().__init__()
        self.cog = cog
        cfg = cog.get_config()
        self.channel_id = discord.ui.TextInput(label="Channel-ID", default=str(cfg.get("channel_id", 0) or ""), required=True, max_length=24)
        self.target_bot_id = discord.ui.TextInput(label="Ziel-Bot-ID", default=str(cfg.get("target_bot_user_id", 0) or ""), required=True, max_length=24)
        self.delete_after = discord.ui.TextInput(label="Löschen nach Minuten", default=str(cfg.get("delete_after_minutes", 120)), required=True, max_length=6)
        self.scan_limit = discord.ui.TextInput(label="Scan-Limit", default=str(cfg.get("scan_limit", 100)), required=True, max_length=6)
        self.add_item(self.channel_id)
        self.add_item(self.target_bot_id)
        self.add_item(self.delete_after)
        self.add_item(self.scan_limit)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            channel_id = int(str(self.channel_id.value).strip())
            target_bot_id = int(str(self.target_bot_id.value).strip())
            delete_after = max(1, int(str(self.delete_after.value).strip()))
            scan_limit = max(1, min(1000, int(str(self.scan_limit.value).strip())))
        except ValueError:
            await interaction.response.send_message("❌ Ungültige Eingabe. IDs und Zahlen müssen numerisch sein.", ephemeral=True)
            return
        self.cog.store.set("channel.autoclear", channel_id)
        self.cog.store.set("autoclear.target_bot_user_id", target_bot_id)
        self.cog.store.set("autoclear.delete_after_minutes", delete_after)
        self.cog.store.set("autoclear.scan_limit", scan_limit)
        await interaction.response.send_message("✅ AutoClear-Setup gespeichert. Öffne `/autoclear panel`, um die aktualisierten Werte zu sehen.", ephemeral=True)


class AutoClearIntervalModal(discord.ui.Modal, title="AutoClear Intervall"):
    def __init__(self, cog: AutoClearCog):
        super().__init__()
        self.cog = cog
        cfg = cog.get_config()
        self.interval = discord.ui.TextInput(label="Intervall in Minuten", default=str(cfg.get("interval_minutes", 30)), required=True, max_length=6)
        self.add_item(self.interval)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            minutes = max(1, int(str(self.interval.value).strip()))
        except ValueError:
            await interaction.response.send_message("❌ Ungültiges Intervall. Beispiel: `30`", ephemeral=True)
            return
        self.cog.store.set("autoclear.schedule_mode", "interval")
        self.cog.store.set("autoclear.interval_minutes", minutes)
        self.cog._last_interval_run = None
        await interaction.response.send_message(f"✅ AutoClear läuft jetzt alle `{minutes}` Minuten.", ephemeral=True)


class AutoClearDailyModal(discord.ui.Modal, title="AutoClear täglicher Zeitplan"):
    def __init__(self, cog: AutoClearCog):
        super().__init__()
        self.cog = cog
        cfg = cog.get_config()
        times = ",".join(cog._normalize_schedule_times(cfg.get("schedule_times", []))) or "04:00"
        self.times = discord.ui.TextInput(label="Uhrzeit(en), z. B. 04:00 oder 04:00,18:30", default=times, required=True, max_length=80)
        self.timezone_name = discord.ui.TextInput(label="Zeitzone", default=str(cfg.get("timezone", "Europe/Berlin")), required=True, max_length=64)
        self.add_item(self.times)
        self.add_item(self.timezone_name)

    async def on_submit(self, interaction: discord.Interaction):
        timezone_name = str(self.timezone_name.value).strip() or "Europe/Berlin"
        times = self.cog._normalize_schedule_times(str(self.times.value).strip())
        if not times:
            await interaction.response.send_message("❌ Keine gültige Uhrzeit erkannt. Beispiel: `04:00`", ephemeral=True)
            return
        self.cog._get_timezone(timezone_name)
        self.cog.store.set("autoclear.schedule_mode", "daily")
        self.cog.store.set("autoclear.schedule_times", times)
        self.cog.store.set("autoclear.timezone", timezone_name)
        await interaction.response.send_message(f"✅ AutoClear läuft täglich um `{', '.join(times)}` (`{timezone_name}`).", ephemeral=True)


class AutoClearListModal(discord.ui.Modal):
    def __init__(self, cog: AutoClearCog, key: str, modal_title: str, done_word: str, remove: bool = False):
        super().__init__(title=modal_title)
        self.cog = cog
        self.key = key
        self.done_word = done_word
        self.remove = remove
        self.text = discord.ui.TextInput(label="Text", placeholder="z. B. RUNDEN-BERICHT:", required=True, max_length=200)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        text = str(self.text.value).strip()
        if not text:
            await interaction.response.send_message("❌ Der Text darf nicht leer sein.", ephemeral=True)
            return
        if self.remove:
            items = self.cog._list_remove(self.key, text)
        else:
            items = self.cog._list_add(self.key, text)
        await interaction.response.send_message(f"✅ `{text}` {self.done_word}. Aktuell: `{len(items)}` Einträge.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoClearCog(bot))
