from __future__ import annotations

import copy
import logging
from io import BytesIO

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from translators import get_translator, get_fallback_translator
from utils.permissions import admin_only, handle_app_command_error


PROVIDER_CHOICES = {"openai", "deepl", "libretranslate"}


class TranslatorTestModal(discord.ui.Modal, title="Translator-Test"):
    text = discord.ui.TextInput(label="Testtext", style=discord.TextStyle.paragraph, max_length=1800)

    def __init__(self, cog: "TranslatorCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            translated_text, used_provider = await self.cog.translate_with_fallback(str(self.text.value))
        except Exception as error:
            logging.exception("Translator-Test fehlgeschlagen: %s", error)
            await interaction.followup.send(f"❌ Translator-Test fehlgeschlagen: `{error}`", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Provider: `{used_provider}`\n\n**Original:**\n{str(self.text.value)[:900]}\n\n**Übersetzung:**\n{translated_text[:1500]}",
            ephemeral=True,
        )


class TranslatorSourceChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog: "TranslatorCog", mode: str):
        self.cog = cog
        self.mode = mode
        label = "Quellkanal hinzufügen" if mode == "add_source" else "Quellkanal entfernen"
        super().__init__(
            placeholder=label,
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        source_ids = list(self.cog.store.get("translator.source_channel_ids", []) or [])
        source_ids = [int(x) for x in source_ids]
        if self.mode == "add_source":
            if channel.id not in source_ids:
                source_ids.append(channel.id)
            self.cog.store.set("translator.source_channel_ids", source_ids)
            msg = f"✅ Quellkanal hinzugefügt: {channel.mention}"
        else:
            source_ids = [x for x in source_ids if x != channel.id]
            self.cog.store.set("translator.source_channel_ids", source_ids)
            msg = f"✅ Quellkanal entfernt: {channel.mention}"
        await interaction.response.edit_message(embed=self.cog.build_status_embed(interaction), view=TranslatorPanelView(self.cog))
        await interaction.followup.send(msg, ephemeral=True)


class TranslatorTargetChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog: "TranslatorCog"):
        self.cog = cog
        super().__init__(
            placeholder="Zielkanal setzen",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        self.cog.store.set("channel.translator_target", int(channel.id))
        await interaction.response.edit_message(embed=self.cog.build_status_embed(interaction), view=TranslatorPanelView(self.cog))
        await interaction.followup.send(f"✅ Zielkanal gesetzt: {channel.mention}", ephemeral=True)


class TranslatorProviderSelect(discord.ui.Select):
    def __init__(self, cog: "TranslatorCog"):
        self.cog = cog
        options = [
            discord.SelectOption(label="OpenAI", value="openai", emoji="🤖"),
            discord.SelectOption(label="DeepL", value="deepl", emoji="🌍"),
            discord.SelectOption(label="LibreTranslate", value="libretranslate", emoji="🧩"),
        ]
        super().__init__(placeholder="Hauptübersetzer auswählen", min_values=1, max_values=1, options=options, row=3)

    async def callback(self, interaction: discord.Interaction):
        provider = self.values[0]
        self.cog.store.set("translator.provider", provider)
        self.cog.reload_translators()
        await interaction.response.edit_message(embed=self.cog.build_status_embed(interaction), view=TranslatorPanelView(self.cog))
        await interaction.followup.send(f"✅ Hauptübersetzer gesetzt: `{provider}`", ephemeral=True)


class TranslatorChannelConfigView(discord.ui.View):
    def __init__(self, cog: "TranslatorCog", mode: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.mode = mode
        if mode in {"add_source", "remove_source"}:
            self.add_item(TranslatorSourceChannelSelect(cog, mode))
        else:
            self.add_item(TranslatorTargetChannelSelect(cog))


class TranslatorProviderConfigView(discord.ui.View):
    def __init__(self, cog: "TranslatorCog", key: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.key = key
        self.add_item(TranslatorProviderValueSelect(cog, key))


class TranslatorProviderValueSelect(discord.ui.Select):
    def __init__(self, cog: "TranslatorCog", key: str):
        self.cog = cog
        self.key = key
        label = "Hauptübersetzer auswählen" if key == "translator.provider" else "Fallback-Übersetzer auswählen"
        options = [
            discord.SelectOption(label="OpenAI", value="openai", emoji="🤖"),
            discord.SelectOption(label="DeepL", value="deepl", emoji="🌍"),
            discord.SelectOption(label="LibreTranslate", value="libretranslate", emoji="🧩"),
        ]
        super().__init__(placeholder=label, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        provider = self.values[0]
        self.cog.store.set(self.key, provider)
        self.cog.reload_translators()
        readable = "Hauptübersetzer" if self.key == "translator.provider" else "Fallback"
        await interaction.response.send_message(f"✅ {readable} gesetzt: `{provider}`", ephemeral=True)


class TranslatorPanelActionSelect(discord.ui.Select):
    def __init__(self, cog: "TranslatorCog"):
        self.cog = cog
        options = [
            discord.SelectOption(label="Quellkanal hinzufügen", value="add_source", emoji="➕", description="Kanal, aus dem übersetzt werden soll"),
            discord.SelectOption(label="Quellkanal entfernen", value="remove_source", emoji="➖", description="Kanal aus der Übersetzungsliste entfernen"),
            discord.SelectOption(label="Zielkanal setzen", value="set_target", emoji="🎯", description="Kanal, in den Übersetzungen gepostet werden"),
            discord.SelectOption(label="Hauptübersetzer setzen", value="set_provider", emoji="🤖"),
            discord.SelectOption(label="Fallback setzen", value="set_fallback", emoji="🧩"),
        ]
        super().__init__(placeholder="Translator-Einstellung auswählen ...", min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        action = self.values[0]
        if action in {"add_source", "remove_source", "set_target"}:
            title = {
                "add_source": "➕ Quellkanal hinzufügen",
                "remove_source": "➖ Quellkanal entfernen",
                "set_target": "🎯 Zielkanal setzen",
            }[action]
            embed = discord.Embed(
                title=title,
                description="Wähle den Discord-Kanal direkt im Dropdown. Keine Channel-ID nötig.",
                color=discord.Color.blue(),
            )
            mode = action if action != "set_target" else "target"
            await interaction.response.send_message(embed=embed, view=TranslatorChannelConfigView(self.cog, mode), ephemeral=True)
        elif action == "set_provider":
            await interaction.response.send_message(
                "🤖 Hauptübersetzer auswählen:",
                view=TranslatorProviderConfigView(self.cog, "translator.provider"),
                ephemeral=True,
            )
        elif action == "set_fallback":
            await interaction.response.send_message(
                "🧩 Fallback-Übersetzer auswählen:",
                view=TranslatorProviderConfigView(self.cog, "translator.fallback_provider"),
                ephemeral=True,
            )


class TranslatorPanelView(discord.ui.View):
    def __init__(self, cog: "TranslatorCog"):
        super().__init__(timeout=300)
        self.cog = cog
        self.add_item(TranslatorPanelActionSelect(cog))

    @discord.ui.button(label="Bot/Webhooks", emoji="🤖", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_bots(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = bool(self.cog.store.get("translator.allow_bot_messages", True))
        self.cog.store.set("translator.allow_bot_messages", not current)
        await interaction.response.edit_message(embed=self.cog.build_status_embed(interaction), view=TranslatorPanelView(self.cog))

    @discord.ui.button(label="Embed", emoji="🧾", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = bool(self.cog.store.get("translator.post_as_embed", False))
        self.cog.store.set("translator.post_as_embed", not current)
        await interaction.response.edit_message(embed=self.cog.build_status_embed(interaction), view=TranslatorPanelView(self.cog))

    @discord.ui.button(label="Original-Link", emoji="🔗", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_original_link(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = bool(self.cog.store.get("translator.add_original_link", True))
        self.cog.store.set("translator.add_original_link", not current)
        await interaction.response.edit_message(embed=self.cog.build_status_embed(interaction), view=TranslatorPanelView(self.cog))

    @discord.ui.button(label="Test", emoji="🧪", style=discord.ButtonStyle.primary, row=0)
    async def test(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TranslatorTestModal(self.cog))

    @discord.ui.button(label="Provider neu laden", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def reload(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cog.reload_translators()
        await interaction.response.edit_message(embed=self.cog.build_status_embed(interaction), view=TranslatorPanelView(self.cog))
        await interaction.followup.send("✅ Übersetzer wurden neu initialisiert.", ephemeral=True)


class TranslatorCog(commands.Cog):
    translate_group = app_commands.Group(name="translate", description="Übersetzungs-Listener verwalten")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.processed_message_ids: set[int] = set()
        self.translator = None
        self.fallback_translator = None
        self.reload_translators()

    @property
    def store(self):
        return self.bot.settings

    def get_config(self) -> dict:
        config = copy.deepcopy(self.bot.config_data.get("translator", {}))
        config.setdefault("discord", {})
        config.setdefault("translation", {})
        config.setdefault("behavior", {})
        config["discord"]["source_channel_ids"] = self.store.get("translator.source_channel_ids", config["discord"].get("source_channel_ids", [])) or []
        config["discord"]["target_channel_id"] = self.store.get("channel.translator_target", config["discord"].get("target_channel_id"))
        config["translation"]["provider"] = self.store.get("translator.provider", config["translation"].get("provider", "openai"))
        config["translation"]["fallback_provider"] = self.store.get("translator.fallback_provider", config["translation"].get("fallback_provider", "libretranslate"))
        for key, default in {
            "allow_bot_messages": True,
            "delete_original": False,
            "post_as_embed": False,
            "add_original_link": True,
            "translate_embeds": True,
            "translate_plain_text": True,
            "min_message_length": 3,
        }.items():
            config["behavior"][key] = self.store.get(f"translator.{key}", config["behavior"].get(key, default))
        return config

    def reload_translators(self) -> None:
        config = self.get_config()
        self.translator = get_translator(config)
        self.fallback_translator = get_fallback_translator(config)

    def get_message_text(self, message: discord.Message) -> str:
        config = self.get_config()
        parts = []
        if config.get("behavior", {}).get("translate_plain_text", True) and message.content:
            parts.append(message.content)
        if config.get("behavior", {}).get("translate_embeds", True):
            for embed in message.embeds:
                if embed.title:
                    parts.append(f"**{embed.title}**")
                if embed.description:
                    parts.append(embed.description)
                for field in embed.fields:
                    if field.name:
                        parts.append(f"**{field.name}**")
                    if field.value:
                        parts.append(field.value)
        return "\n\n".join(parts).strip()

    @staticmethod
    def is_image_url(url: str) -> bool:
        return bool(url) and url.split("?")[0].lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))

    def get_message_media(self, message: discord.Message) -> tuple[list[dict], list[str]]:
        image_files = []
        file_urls = []
        for index, attachment in enumerate(message.attachments, start=1):
            url = attachment.url
            filename = attachment.filename or f"image_{index}.png"
            if (attachment.content_type and attachment.content_type.startswith("image/")) or self.is_image_url(url):
                image_files.append({"url": url, "filename": filename})
            else:
                file_urls.append(url)
        for index, embed in enumerate(message.embeds, start=1):
            if embed.image and embed.image.url:
                image_files.append({"url": embed.image.url, "filename": f"embed_image_{index}.png"})
            if embed.thumbnail and embed.thumbnail.url:
                image_files.append({"url": embed.thumbnail.url, "filename": f"embed_thumbnail_{index}.png"})
            if embed.url and self.is_image_url(embed.url):
                image_files.append({"url": embed.url, "filename": f"embed_url_image_{index}.png"})
        if message.content:
            for index, word in enumerate(message.content.split(), start=1):
                clean_word = word.strip("<>()[]{}")
                if self.is_image_url(clean_word):
                    image_files.append({"url": clean_word, "filename": f"text_image_{index}.png"})
        seen = set()
        unique = []
        for item in image_files:
            if item["url"] not in seen:
                unique.append(item)
                seen.add(item["url"])
        return unique, list(dict.fromkeys(file_urls))

    @staticmethod
    def build_original_link(message: discord.Message) -> str:
        return f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"

    @staticmethod
    def shorten(text: str, limit: int = 900) -> str:
        return text if len(text) <= limit else text[: limit - 3] + "..."

    @staticmethod
    def split_text(text: str, max_length: int = 3900) -> list[str]:
        if len(text) <= max_length:
            return [text]
        chunks = []
        current = ""
        for paragraph in text.split("\n"):
            if len(current) + len(paragraph) + 1 <= max_length:
                current += paragraph + "\n"
            else:
                if current.strip():
                    chunks.append(current.strip())
                if len(paragraph) > max_length:
                    for i in range(0, len(paragraph), max_length):
                        chunks.append(paragraph[i : i + max_length])
                    current = ""
                else:
                    current = paragraph + "\n"
        if current.strip():
            chunks.append(current.strip())
        return chunks

    async def download_discord_file(self, url: str, filename: str) -> discord.File | None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logging.warning("Datei konnte nicht geladen werden: HTTP %s - %s", response.status, url)
                        return None
                    data = await response.read()
            file_buffer = BytesIO(data)
            file_buffer.seek(0)
            return discord.File(file_buffer, filename=filename)
        except Exception as error:
            logging.warning("Fehler beim Laden der Datei: %s", error)
            return None

    async def download_image_files(self, image_files: list[dict], limit: int = 10) -> list[discord.File]:
        files = []
        for index, image in enumerate(image_files[:limit], start=1):
            file = await self.download_discord_file(image.get("url"), image.get("filename") or f"image_{index}.png")
            if file:
                files.append(file)
        return files

    async def translate_with_fallback(self, text: str) -> tuple[str, str]:
        config = self.get_config()
        main_provider = config.get("translation", {}).get("provider", "openai")
        fallback_provider = config.get("translation", {}).get("fallback_provider")
        try:
            translated = await self.translator.translate(text)
            return translated, main_provider
        except Exception as main_error:
            logging.warning("Hauptübersetzer '%s' fehlgeschlagen: %s", main_provider, main_error)
            if self.fallback_translator is None:
                raise main_error
            translated = await self.fallback_translator.translate(text)
            return translated, fallback_provider or "fallback"

    @commands.Cog.listener()
    async def on_ready(self):
        config = self.get_config()
        logging.info(
            "Translator bereit | Hauptübersetzer: %s | Fallback: %s",
            config.get("translation", {}).get("provider", "openai"),
            config.get("translation", {}).get("fallback_provider", "kein Fallback"),
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None:
            return
        if self.bot.user and message.author.id == self.bot.user.id:
            return
        config = self.get_config()
        source_channel_ids = config.get("discord", {}).get("source_channel_ids", [])
        target_channel_id = config.get("discord", {}).get("target_channel_id")
        behavior = config.get("behavior", {})
        allow_bot_messages = behavior.get("allow_bot_messages", True)
        if not source_channel_ids or not target_channel_id:
            return
        source_ids = [int(x) for x in source_channel_ids]
        target_id = int(target_channel_id)
        if message.channel.id == target_id:
            return
        if message.author.bot and not allow_bot_messages:
            return
        if message.id in self.processed_message_ids:
            return
        if message.channel.id not in source_ids:
            return
        self.processed_message_ids.add(message.id)
        logging.info(
            "Translator: Nachricht erkannt | channel=%s | author=%s | bot=%s | webhook=%s",
            message.channel.id,
            getattr(message.author, "id", "unbekannt"),
            bool(message.author.bot),
            bool(message.webhook_id),
        )
        raw_text = self.get_message_text(message)
        image_files, file_urls = self.get_message_media(message)
        image_urls = [item["url"] for item in image_files]
        min_length = behavior.get("min_message_length", 3)
        if len(raw_text.strip()) < min_length and not image_files and not file_urls:
            return
        used_provider = "keine Übersetzung"
        if raw_text.strip():
            try:
                translated_text, used_provider = await self.translate_with_fallback(raw_text)
            except Exception as error:
                logging.exception("Übersetzung fehlgeschlagen: %s", error)
                return
            if not translated_text:
                return
        else:
            translated_text = "📎 Neuer Medienbeitrag ohne Text."
        target_channel = self.bot.get_channel(target_id)
        if target_channel is None:
            logging.warning("Übersetzungs-Zielkanal nicht gefunden: %s", target_channel_id)
            return
        original_link = self.build_original_link(message)
        post_as_embed = behavior.get("post_as_embed", True)
        add_original_link = behavior.get("add_original_link", True)
        show_original_excerpt = behavior.get("show_original_excerpt", True)
        max_embed_description_length = behavior.get("max_embed_description_length", 3900)
        try:
            if post_as_embed:
                chunks = self.split_text(translated_text, max_embed_description_length)
                for index, chunk in enumerate(chunks, start=1):
                    title = "🇩🇪 Übersetzte News" + (f" ({index}/{len(chunks)})" if len(chunks) > 1 else "")
                    embed = discord.Embed(title=title, description=chunk, color=discord.Color.blue())
                    if index == 1 and image_urls:
                        embed.set_image(url=image_urls[0])
                    embed.set_footer(text=f"Quelle: #{message.channel.name} | Übersetzer: {used_provider}")
                    if index == 1 and show_original_excerpt:
                        embed.add_field(name="Original-Auszug", value=self.shorten(raw_text, 900), inline=False)
                    if index == 1 and add_original_link:
                        embed.add_field(name="Original", value=f"[Nachricht öffnen]({original_link})", inline=False)
                    await target_channel.send(embed=embed)
            else:
                chunks = self.split_text(translated_text, 1600)
                discord_files = await self.download_image_files(image_files, limit=10)
                for index, chunk in enumerate(chunks, start=1):
                    output = chunk
                    if index == 1 and file_urls:
                        output += "\n\nAnhänge:\n" + "\n".join(file_urls[:5])
                    if index == 1 and add_original_link:
                        output += f"\n\nOriginal: {original_link}"
                    if index == 1 and discord_files:
                        await target_channel.send(content=output[:2000], files=discord_files)
                    else:
                        await target_channel.send(output[:2000])
        except Exception as error:
            logging.exception("Fehler beim Posten der Übersetzung: %s", error)
            return
        logging.info(
            "Translator: Übersetzung gepostet | source_message=%s | target_channel=%s | provider=%s",
            message.id,
            target_channel_id,
            used_provider,
        )
        if behavior.get("delete_original", False):
            try:
                await message.delete()
            except discord.Forbidden:
                logging.warning("Original konnte nicht gelöscht werden: Rechte fehlen.")
            except Exception as error:
                logging.warning("Original konnte nicht gelöscht werden: %s", error)

    def build_status_embed(self, interaction: discord.Interaction | None = None) -> discord.Embed:
        config = self.get_config()
        guild = interaction.guild if interaction else None
        def ch(cid):
            c = guild.get_channel(int(cid)) if guild and cid else None
            return c.mention if c else f"`{cid}`" if cid else "nicht gesetzt"
        source_ids = config.get("discord", {}).get("source_channel_ids", []) or []
        sources = "\n".join(ch(x) for x in source_ids) or "nicht gesetzt"
        embed = discord.Embed(
            title="🌍 Translator-Panel",
            description=(
                "Alles zum Translator stellst du hier ein: Quellkanäle, Zielkanal, Provider und Webhook-Verhalten.\n\n"
                "**Bot/Webhooks** = auch Nachrichten von anderen Bots/Webhooks übersetzen, z. B. Telegram-/News-Feeds.\n"
                "**Embed-Ausgabe** = Übersetzung als schicke Discord-Box senden. Aus = normale Textnachricht.\n"
                "**Original-Link** = unter der Übersetzung einen Link zur ursprünglichen Nachricht anhängen."
            ),
            color=discord.Color.blue(),
        )
        embed.add_field(name="Provider", value=str(config.get("translation", {}).get("provider", "openai")), inline=True)
        embed.add_field(name="Fallback", value=str(config.get("translation", {}).get("fallback_provider", "kein Fallback")), inline=True)
        embed.add_field(name="Quellkanäle", value=sources, inline=False)
        embed.add_field(name="Zielkanal", value=ch(config.get("discord", {}).get("target_channel_id")), inline=False)
        embed.add_field(
            name="Verhalten",
            value=(
                f"Bot/Webhooks: {'✅' if config.get('behavior', {}).get('allow_bot_messages', True) else '❌'}\n"
                f"Embed-Ausgabe: {'✅' if config.get('behavior', {}).get('post_as_embed', False) else '❌'}\n"
                f"Original-Link: {'✅' if config.get('behavior', {}).get('add_original_link', True) else '❌'}"
            ),
            inline=False,
        )
        embed.set_footer(text="Channel und Optionen werden in data/settings.sqlite gespeichert.")
        return embed

    @translate_group.command(name="panel", description="Öffnet das Translator-Bedienfeld.")
    @admin_only()
    async def translate_panel(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self.build_status_embed(interaction), view=TranslatorPanelView(self), ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        handled = await handle_app_command_error(interaction, error)
        if handled:
            return
        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(TranslatorCog(bot))
