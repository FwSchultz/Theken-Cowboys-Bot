from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class SettingsStore:
    """Kleiner SQLite-Settings-Speicher für Discord-konfigurierbare Werte."""

    def __init__(self, db_path: str | Path = "data/settings.sqlite") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    value_type TEXT NOT NULL DEFAULT 'str',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def _encode(self, value: Any) -> tuple[str, str]:
        if isinstance(value, bool):
            return ("true" if value else "false", "bool")
        if isinstance(value, int):
            return (str(value), "int")
        if isinstance(value, float):
            return (str(value), "float")
        if isinstance(value, (list, dict)):
            return (json.dumps(value, ensure_ascii=False), "json")
        if value is None:
            return ("", "none")
        return (str(value), "str")

    def _decode(self, raw: str, value_type: str) -> Any:
        if value_type == "bool":
            return raw.lower() in {"true", "1", "yes", "ja", "on"}
        if value_type == "int":
            try:
                return int(raw)
            except ValueError:
                return 0
        if value_type == "float":
            try:
                return float(raw)
            except ValueError:
                return 0.0
        if value_type == "json":
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        if value_type == "none":
            return None
        return raw

    def set(self, key: str, value: Any) -> None:
        raw, value_type = self._encode(value)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings(key, value, value_type, updated_at)
                VALUES(?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    value_type=excluded.value_type,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (key, raw, value_type),
            )
            conn.commit()

    def get(self, key: str, default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value, value_type FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return self._decode(row["value"], row["value_type"])

    def delete(self, key: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            conn.commit()
            return cur.rowcount > 0

    def all(self, prefix: str | None = None) -> dict[str, Any]:
        with self._connect() as conn:
            if prefix:
                rows = conn.execute(
                    "SELECT key, value, value_type FROM settings WHERE key LIKE ? ORDER BY key",
                    (f"{prefix}%",),
                ).fetchall()
            else:
                rows = conn.execute("SELECT key, value, value_type FROM settings ORDER BY key").fetchall()
        return {row["key"]: self._decode(row["value"], row["value_type"]) for row in rows}

    def seed_from_config(self, config: dict[str, Any]) -> None:
        """Übernimmt sinnvolle Defaults aus YAML, überschreibt aber bestehende Discord-Settings nicht."""
        defaults: dict[str, Any] = {}

        modules = config.get("modules", {})
        if isinstance(modules, dict):
            for name, module in modules.items():
                if isinstance(module, dict):
                    defaults[f"module.{name}.enabled"] = bool(module.get("enabled", False))

        welcome = config.get("welcome", {})
        leave = config.get("leave", {})
        rules = config.get("rules_accept", {})
        member = config.get("member_logger", {})
        autoclear = config.get("autoclear", {})
        translator = config.get("translator", {})
        translator_discord = translator.get("discord", {}) if isinstance(translator, dict) else {}

        mapping = {
            # Channels / Rollen
            "channel.welcome": welcome.get("channel_id"),
            "channel.leave": leave.get("channel_id"),
            "channel.rules": rules.get("channel_id"),
            "channel.admin_notify": rules.get("admin_notify_channel_id"),
            "channel.memberlog": member.get("log_channel_id"),
            "channel.autoclear": autoclear.get("channel_id"),
            "channel.translator_target": translator_discord.get("target_channel_id"),
            "translator.source_channel_ids": translator_discord.get("source_channel_ids", []),
            "role.guest": rules.get("guest_role_id"),
            "memberlog.tracked_role_ids": member.get("tracked_role_ids", []),

            # Welcome / Leave
            "welcome.enabled": welcome.get("enabled"),
            "welcome.use_embed": welcome.get("use_embed"),
            "welcome.title": welcome.get("title"),
            "welcome.color": welcome.get("color"),
            "welcome.messages": welcome.get("messages", []),
            "leave.enabled": leave.get("enabled"),
            "leave.use_embed": leave.get("use_embed"),
            "leave.title": leave.get("title"),
            "leave.color": leave.get("color"),
            "leave.messages": leave.get("messages", []),

            # Rules
            "rules.enabled": rules.get("enabled"),
            "rules.title": rules.get("title"),
            "rules.description": rules.get("description"),
            "rules.button_label": rules.get("button_label"),
            "rules.success_message": rules.get("success_message"),
            "rules.already_accepted_message": rules.get("already_accepted_message"),
            "rules.notify_admin_user_ids": rules.get("notify_admin_user_ids", []),

            # Memberlog
            "memberlog.enabled": member.get("enabled"),
            "memberlog.event.voice_join": member.get("events", {}).get("voice_join", True),
            "memberlog.event.voice_leave": member.get("events", {}).get("voice_leave", True),
            "memberlog.event.voice_switch": member.get("events", {}).get("voice_switch", True),
            "memberlog.event.server_leave": member.get("events", {}).get("server_leave", True),
            "memberlog.cleanup.enabled": member.get("cleanup", {}).get("enabled", False),
            "memberlog.cleanup.interval_hours": member.get("cleanup", {}).get("interval_hours", 24),
            "memberlog.cleanup.delete_after_hours": member.get("cleanup", {}).get("delete_after_hours", 24),
            "memberlog.cleanup.scan_limit": member.get("cleanup", {}).get("scan_limit", 500),

            # Translator
            "translator.provider": translator.get("translation", {}).get("provider", "openai"),
            "translator.fallback_provider": translator.get("translation", {}).get("fallback_provider", "libretranslate"),
            "translator.allow_bot_messages": translator.get("behavior", {}).get("allow_bot_messages", True),
            "translator.delete_original": translator.get("behavior", {}).get("delete_original", False),
            "translator.post_as_embed": translator.get("behavior", {}).get("post_as_embed", False),
            "translator.add_original_link": translator.get("behavior", {}).get("add_original_link", True),
            "translator.translate_embeds": translator.get("behavior", {}).get("translate_embeds", True),
            "translator.translate_plain_text": translator.get("behavior", {}).get("translate_plain_text", True),
            "translator.min_message_length": translator.get("behavior", {}).get("min_message_length", 3),

            # AutoClear
            "autoclear.enabled": autoclear.get("enabled"),
            "autoclear.target_bot_user_id": autoclear.get("target_bot_user_id"),
            "autoclear.schedule_mode": autoclear.get("schedule", {}).get("mode", "interval"),
            "autoclear.schedule_times": autoclear.get("schedule", {}).get("times", []),
            "autoclear.timezone": autoclear.get("schedule", {}).get("timezone", "Europe/Berlin"),
            "autoclear.interval_minutes": autoclear.get("interval_minutes"),
            "autoclear.delete_after_minutes": autoclear.get("delete_after_minutes"),
            "autoclear.scan_limit": autoclear.get("scan_limit"),
            "autoclear.dry_run": autoclear.get("dry_run"),
            "autoclear.delete_required_contains": autoclear.get("delete_rules", {}).get("required_contains", []),
            "autoclear.keep_contains": autoclear.get("keep_rules", {}).get("contains", []),
        }
        defaults.update({k: v for k, v in mapping.items() if v is not None})

        existing = self.all()
        for key, value in defaults.items():
            if key not in existing:
                self.set(key, value)
