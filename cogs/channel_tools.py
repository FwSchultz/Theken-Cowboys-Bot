from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from discord.ext import commands

from services.settings_store import SettingsStore
from utils.permissions import admin_only, handle_app_command_error


SCOPE_BOT_ONLY = "bot_only"
SCOPE_ALL = "all"


class ChannelClearConfirmView(discord.ui.View):
    def __init__(
        self,
        cog: "ChannelToolsCog",
        requester_id: int,
        title: str,
        channel: discord.TextChannel,
        limit: int,
        only_bot_messages: bool,
        contains: str | None,
        older_than_minutes: int | None,
        preview_result: dict,
    ):
        super().__init__(timeout=120)
        self.cog = cog
        self.requester_id = requester_id
        self.title = title
        self.channel = channel
        self.limit = limit
        self.only_bot_messages = only_bot_messages
        self.contains = contains
        self.older_than_minutes = older_than_minutes
        self.preview_result = preview_result

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("❌ Diese Bestätigung gehört nicht dir.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Löschen bestätigen", emoji="✅", style=discord.ButtonStyle.danger)
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True

        candidate_ids = self.preview_result.get("candidate_ids", [])
        await interaction.response.edit_message(
            content=(
                f"⏳ **{self.title}** läuft jetzt wirklich.\n"
                f"Channel: {self.channel.mention}\n"
                f"Sichere Löschliste aus Vorschau: `{len(candidate_ids)}` Nachricht(en)"
            ),
            view=self,
        )

        result = await self.cog._clear_messages(
            channel=self.channel,
            limit=self.limit,
            only_bot_messages=self.only_bot_messages,
            contains=self.contains,
            older_than_minutes=self.older_than_minutes,
            dry_run=False,
            target_message_ids=candidate_ids,
        )
        await interaction.followup.send(self.cog._format_result(f"✅ {self.title} abgeschlossen", result), ephemeral=True)
        self.stop()

    @discord.ui.button(label="Abbrechen", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="❌ Abgebrochen. Es wurde nichts gelöscht.",
            view=self,
        )
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class ChannelLimitModal(discord.ui.Modal):
    limit = discord.ui.TextInput(label="Scan-Limit", placeholder="1000", default="1000", max_length=8)
    older_than_minutes = discord.ui.TextInput(label="Älter als Minuten", placeholder="0 = egal", default="0", required=False, max_length=10)

    def __init__(self, cog: "ChannelToolsCog", channel: discord.TextChannel, title: str, only_bot_messages: bool):
        super().__init__(title=title[:45])
        self.cog = cog
        self.channel = channel
        self.preview_title = title
        self.only_bot_messages = only_bot_messages

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = max(1, min(int(str(self.limit.value).strip() or "1000"), 1000))
            older = int(str(self.older_than_minutes.value).strip() or "0")
        except ValueError:
            await interaction.response.send_message("❌ Limit/Minuten müssen Zahlen sein.", ephemeral=True)
            return

        await self.cog._send_preview(
            interaction=interaction,
            title=self.preview_title,
            channel=self.channel,
            limit=limit,
            only_bot_messages=self.only_bot_messages,
            older_than_minutes=older if older > 0 else None,
        )


class ChannelContainsClearModal(discord.ui.Modal, title="Nachrichten mit Text löschen"):
    contains = discord.ui.TextInput(label="Enthält Text", placeholder="RUNDEN-BERICHT:", max_length=300)
    limit = discord.ui.TextInput(label="Scan-Limit", placeholder="100", default="100", max_length=8)
    older_than_minutes = discord.ui.TextInput(label="Älter als Minuten", placeholder="0 = egal", default="0", required=False, max_length=10)

    def __init__(self, cog: "ChannelToolsCog", channel: discord.TextChannel, only_bot_messages: bool = True):
        super().__init__()
        self.cog = cog
        self.channel = channel
        self.only_bot_messages = only_bot_messages

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = max(1, min(int(str(self.limit.value).strip() or "100"), 1000))
            older = int(str(self.older_than_minutes.value).strip() or "0")
        except ValueError:
            await interaction.response.send_message("❌ Limit/Minuten müssen Zahlen sein.", ephemeral=True)
            return
        await self.cog._send_preview(
            interaction=interaction,
            title="Channel-Clear-Contains",
            channel=self.channel,
            limit=limit,
            only_bot_messages=self.only_bot_messages,
            contains=str(self.contains.value).strip(),
            older_than_minutes=older if older > 0 else None,
        )


class ChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, view: "ChannelPanelView"):
        super().__init__(
            placeholder="Textkanal auswählen ...",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        )
        self.panel_view = view

    async def callback(self, interaction: discord.Interaction):
        # ChannelSelect liefert je nach Cache-Zustand nicht immer direkt ein
        # discord.TextChannel-Objekt. Darum lösen wir den gewählten Channel
        # zuerst sauber über die ID auf. Das verhindert falsche Ablehnungen
        # wie „Bitte einen normalen Textkanal auswählen“.
        raw_channel = self.values[0]
        channel_id = int(raw_channel.id)

        channel = interaction.guild.get_channel(channel_id) if interaction.guild else None
        if channel is None and interaction.guild is not None:
            try:
                channel = await interaction.guild.fetch_channel(channel_id)
            except discord.HTTPException:
                channel = None

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ Bitte einen normalen Textkanal auswählen. Foren, Threads, Kategorien und Voice-Channels werden nicht unterstützt.",
                ephemeral=True,
            )
            return

        self.panel_view.selected_channel_id = channel.id
        self.panel_view.selected_channel = channel
        logging.info("Channel-Clear Panel: Channel ausgewählt | id=%s | name=%s | type=%s", channel.id, channel.name, channel.type)
        await interaction.response.edit_message(embed=self.panel_view.cog.build_panel_embed(interaction, channel), view=self.panel_view)


class ChannelActionSelect(discord.ui.Select):
    def __init__(self, view: "ChannelPanelView"):
        self.panel_view = view
        options = [
            discord.SelectOption(label="Kompletten Channel leeren", value="all", emoji="🧨", description="Alle Nachrichten im Scan-Limit, mit Vorschau"),
            discord.SelectOption(label="Nur Bot-Nachrichten löschen", value="bot", emoji="🤖", description="Nur Nachrichten von Bots/Webhooks"),
            discord.SelectOption(label="Nachrichten mit Text löschen", value="contains_bot", emoji="🔎", description="Textfilter, Standard: nur Bot-Nachrichten"),
            discord.SelectOption(label="Nachrichten mit Text löschen - alle User", value="contains_all", emoji="⚠️", description="Textfilter auch für normale User"),
        ]
        super().__init__(placeholder="Löschaktion auswählen ...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        channel = self.panel_view.get_selected_channel(interaction)
        if channel is None:
            await interaction.response.send_message("❌ Bitte zuerst oben einen Textkanal auswählen.", ephemeral=True)
            return

        action = self.values[0]
        if action == "all":
            await interaction.response.send_modal(ChannelLimitModal(self.panel_view.cog, channel, "Channel komplett leeren", False))
        elif action == "bot":
            await interaction.response.send_modal(ChannelLimitModal(self.panel_view.cog, channel, "Bot-Nachrichten-Clear", True))
        elif action == "contains_bot":
            await interaction.response.send_modal(ChannelContainsClearModal(self.panel_view.cog, channel, True))
        elif action == "contains_all":
            await interaction.response.send_modal(ChannelContainsClearModal(self.panel_view.cog, channel, False))


class ChannelPanelView(discord.ui.View):
    def __init__(self, cog: "ChannelToolsCog", requester_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.requester_id = requester_id
        self.selected_channel_id: int | None = None
        self.selected_channel: discord.TextChannel | None = None
        self.add_item(ChannelPicker(self))
        self.add_item(ChannelActionSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("❌ Dieses Panel gehört nicht dir.", ephemeral=True)
            return False
        return True

    def get_selected_channel(self, interaction: discord.Interaction) -> discord.TextChannel | None:
        if self.selected_channel is not None:
            return self.selected_channel
        if not self.selected_channel_id or not interaction.guild:
            return None
        channel = interaction.guild.get_channel(self.selected_channel_id)
        return channel if isinstance(channel, discord.TextChannel) else None

    @discord.ui.button(label="Aktualisieren", emoji="🔄", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.cog.build_panel_embed(interaction, self.get_selected_channel(interaction)), view=self)

class ChannelToolsCog(commands.Cog):
    channel_group = app_commands.Group(name="channel-clear", description="Textkanäle sicher bereinigen")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = SettingsStore()

    def _message_text(self, message: discord.Message) -> str:
        """Sammelt Content + Embed-Texte, damit Schutzbegriffe auch in Embeds greifen."""
        parts: list[str] = [message.content or ""]
        for embed in message.embeds:
            parts.append(embed.title or "")
            parts.append(embed.description or "")
            if embed.author and embed.author.name:
                parts.append(embed.author.name)
            if embed.footer and embed.footer.text:
                parts.append(embed.footer.text)
            for field in embed.fields:
                parts.append(field.name or "")
                parts.append(field.value or "")
        return "\n".join(parts)

    def _get_protection_terms(self, channel: discord.TextChannel) -> list[str]:
        """Schützt im AutoClear/ARC-Kanal automatisch die AutoClear-Keep-Begriffe."""
        autoclear_channel_id = self.settings.get("channel.autoclear", 0)
        try:
            autoclear_channel_id = int(autoclear_channel_id or 0)
        except (TypeError, ValueError):
            autoclear_channel_id = 0

        if channel.id != autoclear_channel_id:
            return []

        terms = self.settings.get("autoclear.keep_contains", []) or []
        if not isinstance(terms, list):
            return []
        return [str(term) for term in terms if str(term).strip()]

    def _protection_hits(self, message_text: str, protection_terms: list[str]) -> list[str]:
        lower = message_text.lower()
        return [term for term in protection_terms if term.lower() in lower]

    async def _clear_messages(
        self,
        channel: discord.TextChannel,
        limit: int,
        only_bot_messages: bool,
        contains: str | None,
        older_than_minutes: int | None,
        dry_run: bool,
        target_message_ids: list[int] | None = None,
    ) -> dict:
        limit = max(1, min(limit, 1000))
        checked = matched = deleted = skipped = errors = protected = 0
        now = datetime.now(timezone.utc)
        contains_lower = contains.lower() if contains else None
        protection_terms = self._get_protection_terms(channel)
        protected_hits: dict[str, int] = {}
        candidate_ids: list[int] = []

        # Echte Löschung nutzt exakt die Kandidaten aus der Vorschau.
        # Dadurch wird nach der Button-Bestätigung nicht plötzlich etwas anderes gelöscht.
        if target_message_ids is not None:
            for message_id in target_message_ids:
                checked += 1
                try:
                    message = await channel.fetch_message(int(message_id))
                except discord.NotFound:
                    skipped += 1
                    continue
                except discord.Forbidden:
                    errors += 1
                    logging.error("Channel-Clear: Keine Leserechte für Message-ID %s in #%s", message_id, channel.name)
                    continue
                except discord.HTTPException as error:
                    errors += 1
                    logging.error("Channel-Clear: HTTP-Fehler beim Laden von Message-ID %s: %s", message_id, error)
                    continue

                # Zur Sicherheit Schutzbegriffe auch beim echten Löschen nochmal prüfen.
                hits = self._protection_hits(self._message_text(message), protection_terms)
                if hits:
                    protected += 1
                    for hit in hits:
                        protected_hits[hit] = protected_hits.get(hit, 0) + 1
                    continue

                matched += 1
                try:
                    await message.delete()
                    deleted += 1
                except discord.Forbidden:
                    errors += 1
                    logging.error("Channel-Clear: Keine Rechte für Message-ID %s in #%s", message.id, channel.name)
                except discord.HTTPException as error:
                    errors += 1
                    logging.error("Channel-Clear: HTTP-Fehler bei Message-ID %s: %s", message.id, error)

            result = {
                "checked": checked,
                "matched": matched,
                "deleted": deleted,
                "skipped": skipped,
                "protected": protected,
                "protected_hits": protected_hits,
                "errors": errors,
                "dry_run": dry_run,
                "candidate_ids": [],
                "protection_active": bool(protection_terms),
            }
            self._log_result(channel, result, contains, only_bot_messages)
            return result

        try:
            async for message in channel.history(limit=limit):
                checked += 1

                if only_bot_messages and not message.author.bot:
                    skipped += 1
                    continue

                text = self._message_text(message)

                if contains_lower and contains_lower not in text.lower():
                    skipped += 1
                    continue

                if older_than_minutes is not None:
                    if now - message.created_at < timedelta(minutes=older_than_minutes):
                        skipped += 1
                        continue

                hits = self._protection_hits(text, protection_terms)
                if hits:
                    protected += 1
                    for hit in hits:
                        protected_hits[hit] = protected_hits.get(hit, 0) + 1
                    continue

                matched += 1
                candidate_ids.append(message.id)
                if dry_run:
                    continue
                try:
                    await message.delete()
                    deleted += 1
                except discord.Forbidden:
                    errors += 1
                    logging.error("Channel-Clear: Keine Rechte für Message-ID %s in #%s", message.id, channel.name)
                except discord.HTTPException as error:
                    errors += 1
                    logging.error("Channel-Clear: HTTP-Fehler bei Message-ID %s: %s", message.id, error)
        except discord.Forbidden:
            errors += 1
            logging.error("Channel-Clear: Missing Access beim Lesen von #%s (%s)", channel.name, channel.id)
        except discord.HTTPException as error:
            errors += 1
            logging.error("Channel-Clear: HTTP-Fehler beim Lesen von #%s (%s): %s", channel.name, channel.id, error)

        result = {
            "checked": checked,
            "matched": matched,
            "deleted": deleted,
            "skipped": skipped,
            "protected": protected,
            "protected_hits": protected_hits,
            "errors": errors,
            "dry_run": dry_run,
            "candidate_ids": candidate_ids,
            "protection_active": bool(protection_terms),
        }
        self._log_result(channel, result, contains, only_bot_messages)
        return result

    def _log_result(self, channel: discord.TextChannel, result: dict, contains: str | None, only_bot_messages: bool) -> None:
        logging.info(
            "Channel-Clear abgeschlossen | channel=%s | checked=%s | matched=%s | protected=%s | deleted=%s | dry_run=%s | contains=%r | bot_only=%s",
            channel.id,
            result.get("checked"),
            result.get("matched"),
            result.get("protected"),
            result.get("deleted"),
            result.get("dry_run"),
            contains,
            only_bot_messages,
        )

    def _format_protected_hits(self, result: dict) -> str:
        hits = result.get("protected_hits") or {}
        if not hits:
            return ""
        lines = ["", "Geschützt wegen:"]
        for term, count in sorted(hits.items(), key=lambda item: item[0].lower())[:10]:
            lines.append(f"- `{term}` ({count}x)")
        if len(hits) > 10:
            lines.append(f"- ... plus {len(hits) - 10} weitere")
        return "\n".join(lines)

    def _format_result(self, title: str, result: dict) -> str:
        protection_note = "\nARC/AutoClear-Schutz: `aktiv`" if result.get("protection_active") else ""
        return (
            f"**{title}**\n"
            f"Dry-Run/Vorschau: `{result['dry_run']}`{protection_note}\n"
            f"Geprüft: `{result['checked']}`\n"
            f"Treffer gelöscht/freigegeben: `{result['matched']}`\n"
            f"Gelöscht: `{result['deleted']}`\n"
            f"Geschützt: `{result.get('protected', 0)}`\n"
            f"Übersprungen: `{result['skipped']}`\n"
            f"Fehler: `{result['errors']}`"
            f"{self._format_protected_hits(result)}"
        )

    def _scope_to_bot_only(self, scope: app_commands.Choice[str] | None) -> bool:
        if scope is None:
            return True
        return scope.value != SCOPE_ALL

    def _missing_channel_permissions(self, channel: discord.TextChannel) -> list[str]:
        """Prüft die wichtigsten Rechte für Vorschau und Löschen."""
        me = channel.guild.me
        if me is None:
            return ["Bot-Mitglied konnte nicht ermittelt werden"]

        perms = channel.permissions_for(me)
        missing: list[str] = []
        if not perms.view_channel:
            missing.append("Kanal ansehen")
        if not perms.read_message_history:
            missing.append("Nachrichtenverlauf lesen")
        if not perms.manage_messages:
            missing.append("Nachrichten verwalten")
        return missing

    def _format_missing_permissions(self, channel: discord.TextChannel, missing: list[str]) -> str:
        lines = [
            f"❌ **Channel-Clear kann {channel.mention} nicht bereinigen.**",
            "",
            "Dem Bot fehlen in diesem Kanal folgende Rechte:",
        ]
        lines.extend(f"- `{item}`" for item in missing)
        lines.extend([
            "",
            "Lösung:",
            "Servereinstellungen → Rollen → Bot-Rolle prüfen",
            "und zusätzlich im Kanal unter Berechtigungen kein rotes X für die Bot-Rolle setzen.",
        ])
        return "\n".join(lines)

    async def _send_preview(
        self,
        interaction: discord.Interaction,
        title: str,
        channel: discord.TextChannel,
        limit: int,
        only_bot_messages: bool,
        contains: str | None = None,
        older_than_minutes: int | None = None,
    ):
        missing_permissions = self._missing_channel_permissions(channel)
        if missing_permissions:
            await interaction.response.send_message(
                self._format_missing_permissions(channel, missing_permissions),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        preview = await self._clear_messages(
            channel=channel,
            limit=limit,
            only_bot_messages=only_bot_messages,
            contains=contains,
            older_than_minutes=older_than_minutes,
            dry_run=True,
        )
        scope_text = "nur Bot-Nachrichten" if only_bot_messages else "alle Nachrichten"
        filter_text = f"\nFilter: `{contains}`" if contains else ""
        age_text = f"\nÄlter als: `{older_than_minutes} Minuten`" if older_than_minutes else ""
        protection_text = "\nARC/AutoClear-Schutz: `aktiv`" if preview.get("protection_active") else ""
        message = (
            f"⚠️ **{title} - Vorschau**\n"
            f"Channel: {channel.mention}\n"
            f"Bereich: `{scope_text}`{filter_text}{age_text}{protection_text}\n\n"
            f"Geprüft: `{preview['checked']}`\n"
            f"Würde löschen: `{preview['matched']}`\n"
            f"Geschützt: `{preview.get('protected', 0)}`\n"
            f"Übersprungen: `{preview['skipped']}`\n"
            f"Fehler: `{preview['errors']}`"
            f"{self._format_protected_hits(preview)}"
        )

        if preview["matched"] <= 0 or preview["errors"] > 0:
            await interaction.followup.send(message + "\n\nEs wird kein Bestätigungsbutton angezeigt.", ephemeral=True)
            return

        view = ChannelClearConfirmView(
            cog=self,
            requester_id=interaction.user.id,
            title=title,
            channel=channel,
            limit=limit,
            only_bot_messages=only_bot_messages,
            contains=contains,
            older_than_minutes=older_than_minutes,
            preview_result=preview,
        )
        await interaction.followup.send(
            message + "\n\nZum echten Löschen unten bestätigen. Läuft nach 120 Sekunden ab.",
            view=view,
            ephemeral=True,
        )


    def build_panel_embed(self, interaction: discord.Interaction, selected_channel: discord.TextChannel | None = None) -> discord.Embed:
        autoclear_channel_id = int(self.settings.get("channel.autoclear", 0) or 0)
        autoclear_channel = interaction.guild.get_channel(autoclear_channel_id) if interaction.guild and autoclear_channel_id else None
        protection_active = selected_channel is not None and selected_channel.id == autoclear_channel_id

        embed = discord.Embed(
            title="🧹 Channel-Clear Panel",
            description=(
                "Wähle zuerst einen Textkanal aus. Danach wählst du die Löschart. "
                "Es kommt immer zuerst eine Vorschau und erst danach ein Bestätigungsbutton."
            ),
            color=discord.Color.orange(),
        )
        embed.add_field(
            name="Ausgewählter Channel",
            value=selected_channel.mention if selected_channel else "`noch keiner ausgewählt`",
            inline=False,
        )
        embed.add_field(
            name="AutoClear/ARC-Kanal",
            value=autoclear_channel.mention if isinstance(autoclear_channel, discord.TextChannel) else f"`{autoclear_channel_id}`",
            inline=False,
        )
        embed.add_field(
            name="Schutz",
            value=(
                "🛡️ `aktiv` - ARC/AutoClear-Schutzbegriffe werden beachtet"
                if protection_active else
                "Normaler Channel - kein ARC-Spezialschutz"
            ),
            inline=False,
        )
        embed.add_field(
            name="Aktionen",
            value=(
                "🧨 Kompletten Channel im Scan-Limit leeren\n"
                "🤖 Nur Bot-/Webhook-Nachrichten löschen\n"
                "🔎 Nachrichten mit bestimmtem Text löschen"
            ),
            inline=False,
        )
        embed.set_footer(text="Maximal 1000 Nachrichten pro Lauf. Ältere Discord-Nachrichten können langsamer gelöscht werden.")
        return embed

    @channel_group.command(name="panel", description="Öffnet das Channel-Clear-Bedienfeld.")
    @admin_only()
    async def panel(self, interaction: discord.Interaction):
        view = ChannelPanelView(self, interaction.user.id)
        await interaction.response.send_message(embed=self.build_panel_embed(interaction), view=view, ephemeral=True)

    # ausgeblendet: @channel_group.command(name="clear", description="Zeigt eine Vorschau und löscht nach Button-Bestätigung.")
    @app_commands.describe(
        channel="Textkanal, der bereinigt werden soll",
        limit="Wie viele Nachrichten maximal geprüft werden",
        scope="Nur Bot-Nachrichten oder alle Nachrichten",
    )
    @app_commands.choices(scope=[
        app_commands.Choice(name="Nur Bot-Nachrichten", value=SCOPE_BOT_ONLY),
        app_commands.Choice(name="Alle Nachrichten", value=SCOPE_ALL),
    ])
    @admin_only()
    async def clear(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        limit: app_commands.Range[int, 1, 1000] = 100,
        scope: app_commands.Choice[str] | None = None,
    ):
        only_bot_messages = self._scope_to_bot_only(scope)
        await self._send_preview(interaction, "Channel-Clear", channel, limit, only_bot_messages)

    # ausgeblendet: @channel_group.command(name="clear-contains", description="Vorschau für Nachrichten, die einen bestimmten Text enthalten.")
    @app_commands.describe(
        channel="Textkanal, der bereinigt werden soll",
        contains="Text, der in Nachricht oder Embed enthalten sein muss",
        limit="Wie viele Nachrichten maximal geprüft werden",
        scope="Nur Bot-Nachrichten oder alle Nachrichten",
        older_than_minutes="Optional: nur Nachrichten älter als X Minuten",
    )
    @app_commands.choices(scope=[
        app_commands.Choice(name="Nur Bot-Nachrichten", value=SCOPE_BOT_ONLY),
        app_commands.Choice(name="Alle Nachrichten", value=SCOPE_ALL),
    ])
    @admin_only()
    async def clear_contains(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        contains: str,
        limit: app_commands.Range[int, 1, 1000] = 100,
        scope: app_commands.Choice[str] | None = None,
        older_than_minutes: int = 0,
    ):
        only_bot_messages = self._scope_to_bot_only(scope)
        await self._send_preview(
            interaction=interaction,
            title="Channel-Clear-Contains",
            channel=channel,
            limit=limit,
            only_bot_messages=only_bot_messages,
            contains=contains,
            older_than_minutes=older_than_minutes if older_than_minutes > 0 else None,
        )

    # ausgeblendet: @channel_group.command(name="clear-bot", description="Vorschau für Bot-Nachrichten und Löschen per Button.")
    @app_commands.describe(
        channel="Textkanal, der bereinigt werden soll",
        limit="Wie viele Nachrichten maximal geprüft werden",
    )
    @admin_only()
    async def clear_bot(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        limit: app_commands.Range[int, 1, 1000] = 100,
    ):
        await self._send_preview(interaction, "Bot-Nachrichten-Clear", channel, limit, True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        handled = await handle_app_command_error(interaction, error)
        if handled:
            return
        logging.exception("ChannelTools-Command Fehler: %s", error)
        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(ChannelToolsCog(bot))
