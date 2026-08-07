from __future__ import annotations

import logging
import sqlite3
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.permissions import admin_only, handle_app_command_error, user_has_admin_role


@dataclass
class VoteQuestion:
    id: int
    text: str
    mode: str
    max_choices: int
    position: int
    options: list[tuple[int, str]]


class VoteRepository:
    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS votes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    creator_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    anonymous INTEGER NOT NULL DEFAULT 1,
                    show_live_results INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'draft',
                    channel_id INTEGER,
                    message_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    closed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS vote_questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vote_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'single',
                    max_choices INTEGER NOT NULL DEFAULT 1,
                    position INTEGER NOT NULL,
                    FOREIGN KEY(vote_id) REFERENCES votes(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS vote_options (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    FOREIGN KEY(question_id) REFERENCES vote_questions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS vote_answers (
                    vote_id INTEGER NOT NULL,
                    question_id INTEGER NOT NULL,
                    option_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(vote_id, question_id, option_id, user_id),
                    FOREIGN KEY(vote_id) REFERENCES votes(id) ON DELETE CASCADE,
                    FOREIGN KEY(question_id) REFERENCES vote_questions(id) ON DELETE CASCADE,
                    FOREIGN KEY(option_id) REFERENCES vote_options(id) ON DELETE CASCADE
                );
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(votes)").fetchall()}
            if "closes_at" not in columns:
                conn.execute("ALTER TABLE votes ADD COLUMN closes_at TEXT")
            if "result_role_ids" not in columns:
                conn.execute("ALTER TABLE votes ADD COLUMN result_role_ids TEXT NOT NULL DEFAULT '[]'")
            if "result_message_id" not in columns:
                conn.execute("ALTER TABLE votes ADD COLUMN result_message_id INTEGER")

    def create_vote(self, guild_id: int, creator_id: int, title: str, description: str, anonymous: bool, live: bool) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO votes(guild_id, creator_id, title, description, anonymous, show_live_results) VALUES(?,?,?,?,?,?)",
                (guild_id, creator_id, title, description, int(anonymous), int(live)),
            )
            return int(cur.lastrowid)

    def get_vote(self, vote_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM votes WHERE id=?", (vote_id,)).fetchone()

    def update_deadline(self, vote_id: int, closes_at: datetime | None) -> None:
        value = closes_at.astimezone(timezone.utc).isoformat() if closes_at else None
        with self.connect() as conn:
            conn.execute("UPDATE votes SET closes_at=? WHERE id=?", (value, vote_id))

    def update_result_roles(self, vote_id: int, role_ids: list[int]) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE votes SET result_role_ids=? WHERE id=?", (json.dumps(role_ids), vote_id))

    def due_open_votes(self, now: datetime) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM votes WHERE status='open' AND closes_at IS NOT NULL AND closes_at <= ?",
                (now.astimezone(timezone.utc).isoformat(),),
            ).fetchall()

    def set_result_message(self, vote_id: int, message_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE votes SET result_message_id=? WHERE id=?", (message_id, vote_id))

    def list_votes(self, guild_id: int, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM votes WHERE guild_id=? ORDER BY id DESC LIMIT ?", (guild_id, limit)
            ).fetchall()

    def add_question(self, vote_id: int, text: str, mode: str, max_choices: int, options: list[str]) -> int:
        with self.connect() as conn:
            position = conn.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM vote_questions WHERE vote_id=?", (vote_id,)
            ).fetchone()[0]
            cur = conn.execute(
                "INSERT INTO vote_questions(vote_id,text,mode,max_choices,position) VALUES(?,?,?,?,?)",
                (vote_id, text, mode, max_choices, position),
            )
            qid = int(cur.lastrowid)
            conn.executemany(
                "INSERT INTO vote_options(question_id,text,position) VALUES(?,?,?)",
                [(qid, option, idx) for idx, option in enumerate(options, start=1)],
            )
            return qid

    def questions(self, vote_id: int) -> list[VoteQuestion]:
        with self.connect() as conn:
            qrows = conn.execute(
                "SELECT * FROM vote_questions WHERE vote_id=? ORDER BY position", (vote_id,)
            ).fetchall()
            result: list[VoteQuestion] = []
            for row in qrows:
                options = conn.execute(
                    "SELECT id,text FROM vote_options WHERE question_id=? ORDER BY position", (row["id"],)
                ).fetchall()
                result.append(
                    VoteQuestion(
                        id=int(row["id"]), text=row["text"], mode=row["mode"],
                        max_choices=int(row["max_choices"]), position=int(row["position"]),
                        options=[(int(o["id"]), o["text"]) for o in options],
                    )
                )
            return result

    def delete_question(self, question_id: int) -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT vote_id FROM vote_questions WHERE id=?", (question_id,)).fetchone()
            if not row:
                return
            vote_id = int(row["vote_id"])
            conn.execute("DELETE FROM vote_questions WHERE id=?", (question_id,))
            rows = conn.execute(
                "SELECT id FROM vote_questions WHERE vote_id=? ORDER BY position,id", (vote_id,)
            ).fetchall()
            for idx, item in enumerate(rows, start=1):
                conn.execute("UPDATE vote_questions SET position=? WHERE id=?", (idx, item["id"]))

    def publish(self, vote_id: int, channel_id: int, message_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE votes SET status='open',channel_id=?,message_id=? WHERE id=?",
                (channel_id, message_id, vote_id),
            )

    def close(self, vote_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE votes SET status='closed',closed_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), vote_id),
            )

    def delete_vote(self, vote_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM votes WHERE id=?", (vote_id,))

    def vote_by_message(self, message_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM votes WHERE message_id=?", (message_id,)).fetchone()

    def save_question_answer(self, vote_id: int, question_id: int, user_id: int, option_ids: list[int]) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM vote_answers WHERE vote_id=? AND question_id=? AND user_id=?",
                (vote_id, question_id, user_id),
            )
            conn.executemany(
                "INSERT INTO vote_answers(vote_id,question_id,option_id,user_id) VALUES(?,?,?,?)",
                [(vote_id, question_id, oid, user_id) for oid in option_ids],
            )

    def user_answers(self, vote_id: int, user_id: int) -> dict[int, list[int]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT question_id,option_id FROM vote_answers WHERE vote_id=? AND user_id=?",
                (vote_id, user_id),
            ).fetchall()
        result: dict[int, list[int]] = {}
        for row in rows:
            result.setdefault(int(row["question_id"]), []).append(int(row["option_id"]))
        return result

    def participant_count(self, vote_id: int) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(DISTINCT user_id) FROM vote_answers WHERE vote_id=?", (vote_id,)).fetchone()[0])

    def result_counts(self, vote_id: int) -> dict[int, dict[int, int]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT question_id,option_id,COUNT(*) AS count FROM vote_answers WHERE vote_id=? GROUP BY question_id,option_id",
                (vote_id,),
            ).fetchall()
        result: dict[int, dict[int, int]] = {}
        for row in rows:
            result.setdefault(int(row["question_id"]), {})[int(row["option_id"])] = int(row["count"])
        return result


class CreateVoteModal(discord.ui.Modal, title="Neuen Vote erstellen"):
    vote_title = discord.ui.TextInput(label="Titel", max_length=100, placeholder="Theken-Cowboys Spieleabend")
    description = discord.ui.TextInput(label="Beschreibung", style=discord.TextStyle.paragraph, required=False, max_length=1000)
    anonymous = discord.ui.TextInput(label="Anonym?", default="ja", max_length=10, placeholder="ja/nein")
    live = discord.ui.TextInput(label="Live-Ergebnis sichtbar?", default="nein", max_length=10, placeholder="ja/nein")

    def __init__(self, cog: "VoteCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("❌ Nur auf einem Server möglich.", ephemeral=True)
            return
        yes = {"ja", "yes", "true", "1", "an", "on"}
        vote_id = self.cog.repo.create_vote(
            interaction.guild.id, interaction.user.id, str(self.vote_title), str(self.description),
            str(self.anonymous).strip().lower() in yes, str(self.live).strip().lower() in yes,
        )
        await interaction.response.send_message(
            embed=self.cog.build_editor_embed(vote_id), view=VoteEditorView(self.cog, vote_id), ephemeral=True
        )


class VoteDeadlineModal(discord.ui.Modal, title="Gültigkeit festlegen"):
    duration = discord.ui.TextInput(
        label="Laufzeit",
        placeholder="z. B. 2h, 3d oder 90m",
        default="24h",
        max_length=20,
    )

    def __init__(self, cog: "VoteCog", vote_id: int):
        super().__init__()
        self.cog = cog
        self.vote_id = vote_id

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.duration).strip().lower().replace(" ", "")
        units = {"m": 60, "h": 3600, "d": 86400}
        try:
            unit = raw[-1]
            amount = int(raw[:-1])
            seconds = amount * units[unit]
        except (ValueError, KeyError, IndexError):
            await interaction.response.send_message("❌ Nutze z. B. `90m`, `24h` oder `7d`.", ephemeral=True)
            return
        if seconds < 300 or seconds > 90 * 86400:
            await interaction.response.send_message("❌ Erlaubt sind 5 Minuten bis 90 Tage.", ephemeral=True)
            return
        self.cog.repo.update_deadline(self.vote_id, datetime.now(timezone.utc) + timedelta(seconds=seconds))
        await interaction.response.edit_message(embed=self.cog.build_editor_embed(self.vote_id), view=VoteEditorView(self.cog, self.vote_id))


class ResultRoleSelect(discord.ui.RoleSelect):
    def __init__(self, cog: "VoteCog", vote_id: int):
        super().__init__(placeholder="Rollen für vorzeitige Auswertung", min_values=0, max_values=10)
        self.cog = cog
        self.vote_id = vote_id

    async def callback(self, interaction: discord.Interaction):
        role_ids = [int(role.id) for role in self.values if not role.is_default()]
        self.cog.repo.update_result_roles(self.vote_id, role_ids)
        labels = ", ".join(role.mention for role in self.values if not role.is_default()) or "nur Administratoren"
        await interaction.response.edit_message(content=f"✅ Auswertung erlaubt für: {labels}", view=None)


class ResultRoleView(discord.ui.View):
    def __init__(self, cog: "VoteCog", vote_id: int):
        super().__init__(timeout=180)
        self.add_item(ResultRoleSelect(cog, vote_id))


class AddQuestionModal(discord.ui.Modal, title="Frage hinzufügen"):
    question = discord.ui.TextInput(label="Frage", max_length=200)
    options = discord.ui.TextInput(label="Antworten – eine pro Zeile", style=discord.TextStyle.paragraph, max_length=1500)
    mode = discord.ui.TextInput(label="Auswahlart", default="einzel", placeholder="einzel oder mehrfach", max_length=20)
    maximum = discord.ui.TextInput(label="Maximale Antworten", default="1", max_length=2)

    def __init__(self, cog: "VoteCog", vote_id: int):
        super().__init__()
        self.cog = cog
        self.vote_id = vote_id

    async def on_submit(self, interaction: discord.Interaction):
        options = [line.strip(" -•\t") for line in str(self.options).splitlines() if line.strip(" -•\t")]
        if not 2 <= len(options) <= 25:
            await interaction.response.send_message("❌ Es sind 2 bis 25 Antworten erlaubt.", ephemeral=True)
            return
        raw_mode = str(self.mode).strip().lower()
        multi = raw_mode in {"mehrfach", "multi", "multiple", "mehrere"}
        try:
            maximum = int(str(self.maximum).strip())
        except ValueError:
            maximum = 1
        maximum = max(1, min(maximum, len(options))) if multi else 1
        self.cog.repo.add_question(self.vote_id, str(self.question), "multi" if multi else "single", maximum, options)
        await interaction.response.edit_message(
            embed=self.cog.build_editor_embed(self.vote_id), view=VoteEditorView(self.cog, self.vote_id)
        )


class DeleteQuestionSelect(discord.ui.Select):
    def __init__(self, cog: "VoteCog", vote_id: int):
        self.cog = cog
        self.vote_id = vote_id
        questions = cog.repo.questions(vote_id)
        options = [discord.SelectOption(label=f"{q.position}. {q.text}"[:100], value=str(q.id)) for q in questions[:25]]
        super().__init__(placeholder="Frage zum Löschen auswählen", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        self.cog.repo.delete_question(int(self.values[0]))
        await interaction.response.edit_message(
            embed=self.cog.build_editor_embed(self.vote_id), view=VoteEditorView(self.cog, self.vote_id)
        )


class DeleteQuestionView(discord.ui.View):
    def __init__(self, cog: "VoteCog", vote_id: int):
        super().__init__(timeout=180)
        self.add_item(DeleteQuestionSelect(cog, vote_id))


class PublishChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog: "VoteCog", vote_id: int):
        super().__init__(placeholder="Zielkanal auswählen", channel_types=[discord.ChannelType.text, discord.ChannelType.news])
        self.cog = cog
        self.vote_id = vote_id

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("❌ Nur auf einem Server möglich.", ephemeral=True)
            return

        selected = self.values[0]
        channel_id = getattr(selected, "id", None)
        if channel_id is None:
            await interaction.response.send_message("❌ Der Zielkanal konnte nicht erkannt werden.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await interaction.guild.fetch_channel(int(channel_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None

        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("❌ Dieser Kanal unterstützt keine normalen Nachrichten.", ephemeral=True)
            return

        me = interaction.guild.me
        if me is None:
            await interaction.response.send_message("❌ Die Bot-Rechte konnten nicht geprüft werden.", ephemeral=True)
            return

        permissions = channel.permissions_for(me)
        if not permissions.view_channel or not permissions.send_messages or not permissions.embed_links:
            await interaction.response.send_message(
                "❌ Mir fehlen in diesem Kanal Rechte: Kanal ansehen, Nachrichten senden oder Links einbetten.",
                ephemeral=True,
            )
            return

        vote = self.cog.repo.get_vote(self.vote_id)
        questions = self.cog.repo.questions(self.vote_id)
        if not vote or not questions:
            await interaction.response.send_message("❌ Vote oder Fragen fehlen.", ephemeral=True)
            return
        if not vote["closes_at"]:
            await interaction.response.send_message("❌ Lege vor der Veröffentlichung eine Gültigkeit fest.", ephemeral=True)
            return

        try:
            message = await channel.send(
                embed=self.cog.build_public_embed(self.vote_id),
                view=PublicVoteView(self.cog),
            )
        except discord.Forbidden:
            await interaction.response.send_message("❌ Ich darf in diesem Kanal keine Nachricht senden.", ephemeral=True)
            return
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"❌ Veröffentlichung fehlgeschlagen: {exc}", ephemeral=True)
            return

        self.cog.repo.publish(self.vote_id, channel.id, message.id)
        await interaction.response.edit_message(
            content=f"✅ Vote veröffentlicht: {message.jump_url}", embed=None, view=None
        )


class PublishChannelView(discord.ui.View):
    def __init__(self, cog: "VoteCog", vote_id: int):
        super().__init__(timeout=180)
        self.add_item(PublishChannelSelect(cog, vote_id))


class VoteEditorView(discord.ui.View):
    def __init__(self, cog: "VoteCog", vote_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.vote_id = vote_id

    @discord.ui.button(label="Frage hinzufügen", emoji="➕", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddQuestionModal(self.cog, self.vote_id))

    @discord.ui.button(label="Frage löschen", emoji="🗑️", style=discord.ButtonStyle.secondary)
    async def delete_question(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.repo.questions(self.vote_id):
            await interaction.response.send_message("Keine Fragen vorhanden.", ephemeral=True)
            return
        await interaction.response.send_message("Welche Frage soll gelöscht werden?", view=DeleteQuestionView(self.cog, self.vote_id), ephemeral=True)

    @discord.ui.button(label="Veröffentlichen", emoji="📢", style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.repo.questions(self.vote_id):
            await interaction.response.send_message("❌ Füge zuerst mindestens eine Frage hinzu.", ephemeral=True)
            return
        await interaction.response.send_message("Wähle den Zielkanal:", view=PublishChannelView(self.cog, self.vote_id), ephemeral=True)

    @discord.ui.button(label="Gültigkeit", emoji="⏳", style=discord.ButtonStyle.secondary, row=1)
    async def deadline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VoteDeadlineModal(self.cog, self.vote_id))

    @discord.ui.button(label="Auswertungsrollen", emoji="🔐", style=discord.ButtonStyle.secondary, row=1)
    async def result_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Wähle Rollen, die Ergebnisse vor Ablauf ansehen dürfen. Administratoren sind immer berechtigt.",
            view=ResultRoleView(self.cog, self.vote_id), ephemeral=True
        )

    @discord.ui.button(label="Aktualisieren", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.cog.build_editor_embed(self.vote_id), view=self)


class VoteListSelect(discord.ui.Select):
    def __init__(self, cog: "VoteCog", guild_id: int):
        self.cog = cog
        rows = cog.repo.list_votes(guild_id)
        options = [
            discord.SelectOption(label=f"#{r['id']} {r['title']}"[:100], value=str(r["id"]), description=str(r["status"])[:100])
            for r in rows[:25]
        ]
        super().__init__(placeholder="Vote auswählen", options=options)

    async def callback(self, interaction: discord.Interaction):
        vote_id = int(self.values[0])
        vote = self.cog.repo.get_vote(vote_id)
        if not vote:
            await interaction.response.send_message("❌ Vote nicht gefunden.", ephemeral=True)
            return
        if vote["status"] == "draft":
            await interaction.response.edit_message(embed=self.cog.build_editor_embed(vote_id), view=VoteEditorView(self.cog, vote_id))
        else:
            await interaction.response.edit_message(embed=self.cog.build_manage_embed(vote_id), view=VoteManageView(self.cog, vote_id))


class VoteListView(discord.ui.View):
    def __init__(self, cog: "VoteCog", guild_id: int):
        super().__init__(timeout=300)
        rows = cog.repo.list_votes(guild_id)
        if rows:
            self.add_item(VoteListSelect(cog, guild_id))


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, cog: "VoteCog", vote_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.vote_id = vote_id

    @discord.ui.button(label="Endgültig löschen", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cog.repo.delete_vote(self.vote_id)
        await interaction.response.edit_message(content="✅ Vote gelöscht.", embed=None, view=None)


class VoteManageView(discord.ui.View):
    def __init__(self, cog: "VoteCog", vote_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.vote_id = vote_id

    @discord.ui.button(label="Ergebnis", emoji="📊", style=discord.ButtonStyle.primary)
    async def result(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.can_view_early_results(interaction, self.vote_id):
            await interaction.response.send_message("⛔ Für die vorzeitige Auswertung fehlen dir die Rechte.", ephemeral=True)
            return
        await interaction.response.send_message(embed=self.cog.build_results_embed(self.vote_id), ephemeral=True)

    @discord.ui.button(label="Beenden", emoji="🔒", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not user_has_admin_role(interaction):
            await interaction.response.send_message("⛔ Nur Administratoren dürfen Votes vorzeitig beenden.", ephemeral=True)
            return
        vote = self.cog.repo.get_vote(self.vote_id)
        if not vote:
            await interaction.response.edit_message(
                content="❌ Dieser Vote existiert nicht mehr. Öffne das Vote-Panel erneut.",
                embed=None,
                view=None,
            )
            return
        if vote["status"] != "open":
            await interaction.response.send_message(
                "ℹ️ Nur ein veröffentlichter, offener Vote kann beendet werden.",
                ephemeral=True,
            )
            return
        await self.cog.close_and_publish_results(self.vote_id, automatic=False)
        updated_vote = self.cog.repo.get_vote(self.vote_id)
        if not updated_vote:
            await interaction.response.edit_message(
                content="❌ Der Vote wurde während der Verarbeitung entfernt.",
                embed=None,
                view=None,
            )
            return
        await interaction.response.edit_message(embed=self.cog.build_manage_embed(self.vote_id), view=self)

    @discord.ui.button(label="Löschen", emoji="🗑️", style=discord.ButtonStyle.secondary)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⚠️ Der Vote und alle Stimmen werden gelöscht.", view=ConfirmDeleteView(self.cog, self.vote_id), ephemeral=True)


class AnswerSelect(discord.ui.Select):
    def __init__(self, cog: "VoteCog", vote_id: int, question: VoteQuestion, index: int, selected: list[int]):
        self.cog = cog
        self.vote_id = vote_id
        self.question = question
        self.index = index
        options = [discord.SelectOption(label=text[:100], value=str(oid), default=oid in selected) for oid, text in question.options]
        max_values = 1 if question.mode == "single" else min(question.max_choices, len(options))
        super().__init__(placeholder="Antwort auswählen", options=options, min_values=1, max_values=max_values)

    async def callback(self, interaction: discord.Interaction):
        self.cog.repo.save_question_answer(self.vote_id, self.question.id, interaction.user.id, [int(v) for v in self.values])
        questions = self.cog.repo.questions(self.vote_id)
        next_index = self.index + 1
        if next_index < len(questions):
            answers = self.cog.repo.user_answers(self.vote_id, interaction.user.id)
            await interaction.response.edit_message(
                embed=self.cog.build_question_embed(self.vote_id, questions[next_index], next_index, len(questions)),
                view=AnswerQuestionView(self.cog, self.vote_id, questions[next_index], next_index, answers.get(questions[next_index].id, [])),
            )
        else:
            await interaction.response.edit_message(embed=self.cog.build_summary_embed(self.vote_id, interaction.user.id), view=VoteSummaryView(self.cog, self.vote_id))
            vote = self.cog.repo.get_vote(self.vote_id)
            if vote and vote["show_live_results"]:
                await self.cog.refresh_public_message(self.vote_id)


class AnswerQuestionView(discord.ui.View):
    def __init__(self, cog: "VoteCog", vote_id: int, question: VoteQuestion, index: int, selected: list[int]):
        super().__init__(timeout=600)
        self.add_item(AnswerSelect(cog, vote_id, question, index, selected))


class VoteSummaryView(discord.ui.View):
    def __init__(self, cog: "VoteCog", vote_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.vote_id = vote_id

    @discord.ui.button(label="Auswahl ändern", emoji="✏️", style=discord.ButtonStyle.secondary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        questions = self.cog.repo.questions(self.vote_id)
        answers = self.cog.repo.user_answers(self.vote_id, interaction.user.id)
        if not questions:
            await interaction.response.send_message("❌ Keine Fragen vorhanden.", ephemeral=True)
            return
        q = questions[0]
        await interaction.response.edit_message(
            embed=self.cog.build_question_embed(self.vote_id, q, 0, len(questions)),
            view=AnswerQuestionView(self.cog, self.vote_id, q, 0, answers.get(q.id, [])),
        )


class PublicVoteView(discord.ui.View):
    def __init__(self, cog: "VoteCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Abstimmen", emoji="🗳️", style=discord.ButtonStyle.primary, custom_id="tc_vote:participate")
    async def participate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.message:
            await interaction.response.send_message("❌ Vote konnte nicht zugeordnet werden.", ephemeral=True)
            return
        vote = self.cog.repo.vote_by_message(interaction.message.id)
        if not vote or vote["status"] != "open":
            await interaction.response.send_message("🔒 Dieser Vote ist beendet oder nicht mehr verfügbar.", ephemeral=True)
            return
        questions = self.cog.repo.questions(int(vote["id"]))
        answers = self.cog.repo.user_answers(int(vote["id"]), interaction.user.id)
        if not questions:
            await interaction.response.send_message("❌ Der Vote enthält keine Fragen.", ephemeral=True)
            return
        q = questions[0]
        await interaction.response.send_message(
            embed=self.cog.build_question_embed(int(vote["id"]), q, 0, len(questions)),
            view=AnswerQuestionView(self.cog, int(vote["id"]), q, 0, answers.get(q.id, [])), ephemeral=True
        )

    @discord.ui.button(label="Ergebnis", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="tc_vote:results")
    async def results(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.message:
            return
        vote = self.cog.repo.vote_by_message(interaction.message.id)
        if not vote:
            await interaction.response.send_message("❌ Vote nicht gefunden.", ephemeral=True)
            return
        allowed = bool(vote["show_live_results"]) or vote["status"] == "closed" or self.cog.can_view_early_results(interaction, int(vote["id"]))
        if not allowed:
            await interaction.response.send_message("📊 Das Ergebnis wird erst nach Ende der Abstimmung angezeigt.", ephemeral=True)
            return
        await interaction.response.send_message(embed=self.cog.build_results_embed(int(vote["id"])), ephemeral=True)


class VotePanelView(discord.ui.View):
    def __init__(self, cog: "VoteCog"):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="Neuen Vote erstellen", emoji="➕", style=discord.ButtonStyle.primary)
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateVoteModal(self.cog))

    @discord.ui.button(label="Votes verwalten", emoji="🗂️", style=discord.ButtonStyle.secondary)
    async def manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        rows = self.cog.repo.list_votes(interaction.guild.id)
        if not rows:
            await interaction.response.send_message("Noch keine Votes vorhanden.", ephemeral=True)
            return
        await interaction.response.send_message("Vote auswählen:", view=VoteListView(self.cog, interaction.guild.id), ephemeral=True)


class VoteCog(commands.Cog):
    vote_group = app_commands.Group(name="vote", description="Mehrstufige Abstimmungen erstellen und verwalten")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.repo = VoteRepository(str(bot.settings.db_path))
        bot.add_view(PublicVoteView(self))
        self.deadline_watcher.start()

    def cog_unload(self):
        self.deadline_watcher.cancel()

    def parse_role_ids(self, vote: sqlite3.Row) -> set[int]:
        try:
            return {int(x) for x in json.loads(vote["result_role_ids"] or "[]")}
        except (ValueError, TypeError, json.JSONDecodeError):
            return set()

    def can_view_early_results(self, interaction: discord.Interaction, vote_id: int) -> bool:
        if user_has_admin_role(interaction):
            return True
        vote = self.repo.get_vote(vote_id)
        if not vote or not isinstance(interaction.user, discord.Member):
            return False
        allowed = self.parse_role_ids(vote)
        return bool(allowed.intersection(role.id for role in interaction.user.roles))

    def result_roles_text(self, vote: sqlite3.Row) -> str:
        role_ids = self.parse_role_ids(vote)
        return ", ".join(f"<@&{rid}>" for rid in role_ids) if role_ids else "nur Administratoren"

    def format_deadline(self, value: str | None) -> str:
        if not value:
            return "nicht festgelegt"
        try:
            dt = datetime.fromisoformat(value)
            return f"<t:{int(dt.timestamp())}:F> (<t:{int(dt.timestamp())}:R>)"
        except ValueError:
            return "ungültig"

    async def close_and_publish_results(self, vote_id: int, automatic: bool) -> None:
        vote = self.repo.get_vote(vote_id)
        if not vote or vote["status"] != "open":
            return
        self.repo.close(vote_id)
        await self.refresh_public_message(vote_id)
        channel = self.bot.get_channel(int(vote["channel_id"])) if vote["channel_id"] else None
        if isinstance(channel, (discord.TextChannel, discord.Thread)) and not vote["result_message_id"]:
            try:
                text = "⏰ Die Abstimmung wurde automatisch beendet." if automatic else "🔒 Die Abstimmung wurde vorzeitig beendet."
                msg = await channel.send(content=text, embed=self.build_results_embed(vote_id))
                self.repo.set_result_message(vote_id, msg.id)
            except discord.HTTPException:
                logging.exception("Automatische Vote-Auswertung für %s konnte nicht gesendet werden", vote_id)

    @tasks.loop(seconds=60)
    async def deadline_watcher(self):
        for vote in self.repo.due_open_votes(datetime.now(timezone.utc)):
            await self.close_and_publish_results(int(vote["id"]), automatic=True)

    @deadline_watcher.before_loop
    async def before_deadline_watcher(self):
        await self.bot.wait_until_ready()

    def build_panel_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🗳️ Vote-Panel",
            description="Erstelle mehrstufige Abstimmungen mit Einzel- oder Mehrfachauswahl pro Frage.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Ablauf", value="1. Vote anlegen\n2. Fragen hinzufügen\n3. Zielkanal wählen\n4. Veröffentlichen", inline=False)
        embed.add_field(name="Speicherung", value="Entwürfe, Fragen und Stimmen werden in SQLite gespeichert.", inline=False)
        return embed

    def build_editor_embed(self, vote_id: int) -> discord.Embed:
        vote = self.repo.get_vote(vote_id)
        questions = self.repo.questions(vote_id)
        if not vote:
            return discord.Embed(title="Vote nicht gefunden", color=discord.Color.red())
        embed = discord.Embed(title=f"🛠️ Vote-Entwurf #{vote_id}: {vote['title']}", description=vote["description"] or "Keine Beschreibung", color=discord.Color.orange())
        closes = self.format_deadline(vote["closes_at"])
        roles = self.result_roles_text(vote)
        embed.add_field(name="Einstellungen", value=f"Anonym: {'Ja' if vote['anonymous'] else 'Nein'}\nLive-Ergebnis: {'Ja' if vote['show_live_results'] else 'Nein'}\nGültig bis: {closes}\nVorzeitige Auswertung: {roles}", inline=False)
        if questions:
            lines = []
            for q in questions:
                mode = "Einzelwahl" if q.mode == "single" else f"Mehrfachwahl, max. {q.max_choices}"
                lines.append(f"**{q.position}. {q.text}**\n{mode} · {len(q.options)} Antworten")
            embed.add_field(name=f"Fragen ({len(questions)})", value="\n\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="Fragen", value="Noch keine Frage vorhanden.", inline=False)
        return embed

    def build_public_embed(self, vote_id: int) -> discord.Embed:
        vote = self.repo.get_vote(vote_id)
        if not vote:
            return discord.Embed(
                title="❌ Vote nicht gefunden",
                description="Dieser Vote wurde gelöscht oder ist nicht mehr verfügbar.",
                color=discord.Color.red(),
            )
        questions = self.repo.questions(vote_id)
        participants = self.repo.participant_count(vote_id)
        closed = vote["status"] == "closed"
        embed = discord.Embed(title=f"🗳️ {vote['title']}", description=vote["description"] or None, color=discord.Color.dark_grey() if closed else discord.Color.blurple())
        lines = []
        for q in questions:
            mode = "eine Antwort" if q.mode == "single" else f"bis zu {q.max_choices} Antworten"
            lines.append(f"**{q.position}. {q.text}** — {mode}")
        embed.add_field(name=f"Fragen ({len(questions)})", value="\n".join(lines)[:1024], inline=False)
        embed.add_field(name="Status", value="🔒 Beendet" if closed else "🟢 Offen", inline=True)
        embed.add_field(name="Teilnehmer", value=str(participants), inline=True)
        embed.add_field(name="Gültig bis", value=self.format_deadline(vote["closes_at"]), inline=True)
        if vote["show_live_results"] or closed:
            embed.add_field(name="Ergebnisse", value="Über den Button **Ergebnis** abrufbar.", inline=False)
        else:
            embed.add_field(name="Ergebnisse", value="Werden nach Ende der Abstimmung sichtbar.", inline=False)
        embed.set_footer(text=f"Vote-ID: {vote_id}")
        return embed

    def build_manage_embed(self, vote_id: int) -> discord.Embed:
        vote = self.repo.get_vote(vote_id)
        if not vote:
            return discord.Embed(
                title="❌ Vote nicht gefunden",
                description="Öffne das Vote-Panel erneut und wähle einen vorhandenen Vote aus.",
                color=discord.Color.red(),
            )
        embed = self.build_public_embed(vote_id)
        embed.title = f"⚙️ Verwaltung: {vote['title']}"
        if vote["channel_id"] and vote["message_id"]:
            embed.add_field(name="Nachricht", value=f"<#{vote['channel_id']}> · `{vote['message_id']}`", inline=False)
        return embed

    def build_question_embed(self, vote_id: int, q: VoteQuestion, index: int, total: int) -> discord.Embed:
        vote = self.repo.get_vote(vote_id)
        mode = "Wähle genau eine Antwort." if q.mode == "single" else f"Wähle eine bis {q.max_choices} Antworten."
        return discord.Embed(title=f"{vote['title']} · Frage {index + 1}/{total}", description=f"**{q.text}**\n\n{mode}", color=discord.Color.blurple())

    def build_summary_embed(self, vote_id: int, user_id: int) -> discord.Embed:
        vote = self.repo.get_vote(vote_id)
        questions = self.repo.questions(vote_id)
        answers = self.repo.user_answers(vote_id, user_id)
        embed = discord.Embed(title="✅ Stimme gespeichert", description=f"Deine Auswahl für **{vote['title']}**:", color=discord.Color.green())
        for q in questions:
            chosen = set(answers.get(q.id, []))
            labels = [text for oid, text in q.options if oid in chosen]
            embed.add_field(name=f"{q.position}. {q.text}", value=", ".join(labels) or "Keine Auswahl", inline=False)
        embed.set_footer(text="Du kannst deine Auswahl bis zum Ende des Votes ändern.")
        return embed

    def build_results_embed(self, vote_id: int) -> discord.Embed:
        vote = self.repo.get_vote(vote_id)
        if not vote:
            return discord.Embed(
                title="❌ Vote nicht gefunden",
                description="Eine Auswertung ist nicht möglich, weil der Vote nicht mehr existiert.",
                color=discord.Color.red(),
            )
        questions = self.repo.questions(vote_id)
        counts = self.repo.result_counts(vote_id)
        participants = self.repo.participant_count(vote_id)
        embed = discord.Embed(title=f"📊 Ergebnis: {vote['title']}", description=f"Teilnehmer: **{participants}**", color=discord.Color.green())
        for q in questions:
            qcounts = counts.get(q.id, {})
            lines = [f"{text}: **{qcounts.get(oid, 0)}**" for oid, text in q.options]
            embed.add_field(name=f"{q.position}. {q.text}", value="\n".join(lines)[:1024], inline=False)
        return embed

    async def refresh_public_message(self, vote_id: int) -> None:
        vote = self.repo.get_vote(vote_id)
        if not vote or not vote["channel_id"] or not vote["message_id"]:
            return
        channel = self.bot.get_channel(int(vote["channel_id"]))
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            message = await channel.fetch_message(int(vote["message_id"]))
            await message.edit(embed=self.build_public_embed(vote_id), view=PublicVoteView(self))
        except discord.HTTPException:
            logging.exception("Vote-Nachricht %s konnte nicht aktualisiert werden", vote["message_id"])

    @vote_group.command(name="panel", description="Öffnet das Vote-Bedienfeld.")
    @admin_only()
    async def panel(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self.build_panel_embed(), view=VotePanelView(self), ephemeral=True)

    @vote_group.command(name="ergebnis", description="Zeigt das Ergebnis eines Votes anhand der Vote-ID.")
    @app_commands.describe(vote_id="Die Vote-ID aus der Fußzeile")
    async def result_cmd(self, interaction: discord.Interaction, vote_id: int):
        vote = self.repo.get_vote(vote_id)
        if not vote or not interaction.guild or int(vote["guild_id"]) != interaction.guild.id:
            await interaction.response.send_message("❌ Vote nicht gefunden.", ephemeral=True)
            return
        allowed = bool(vote["show_live_results"]) or vote["status"] == "closed" or self.cog.can_view_early_results(interaction, int(vote["id"]))
        if not allowed:
            await interaction.response.send_message("📊 Das Ergebnis wird erst nach Ende angezeigt.", ephemeral=True)
            return
        await interaction.response.send_message(embed=self.build_results_embed(vote_id), ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if await handle_app_command_error(interaction, error):
            return
        logging.exception("Vote-Command Fehler: %s", error)
        if interaction.response.is_done():
            await interaction.followup.send(f"❌ Vote-Fehler: {error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Vote-Fehler: {error}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VoteCog(bot))
