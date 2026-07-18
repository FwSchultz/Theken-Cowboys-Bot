import json
from datetime import datetime
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils.permissions import admin_only, handle_app_command_error

CONFIG: dict[str, Any] = {}
CONFIG_FILE = "config/audit.yaml"
REPORT_DIR = Path("reports")
REPORT_DIR.mkdir(exist_ok=True)


def set_config(config: dict[str, Any]) -> None:
    global CONFIG
    CONFIG = config


def config_summary(config: dict[str, Any]) -> str:
    def section_count(name: str) -> int:
        value = config.get(name, {})
        return len(value) if isinstance(value, dict) else 0

    rules = config.get("rules", [])
    rules_count = len(rules) if isinstance(rules, list) else 0

    return (
        f"Rollen={section_count('roles')}, "
        f"Text-Channels={section_count('channels')}, "
        f"Kategorien={section_count('categories')}, "
        f"Foren={section_count('forums')}, "
        f"Voice-Channels={section_count('voice_channels')}, "
        f"Regeln={rules_count}"
    )


# ------------------------------------------------------------
# Kleine Helfer
# ------------------------------------------------------------
def normalize_name(value: str | None) -> str:
    return (value or "").lower().strip()


def listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def get_config_section(name: str) -> dict[str, Any]:
    value = CONFIG.get(name, {})
    return value if isinstance(value, dict) else {}


def get_roles_config() -> dict[str, str]:
    return {str(k): str(v) for k, v in get_config_section("roles").items()}


def get_resources_config() -> dict[str, dict[str, str]]:
    return {
        "channels": {str(k): str(v) for k, v in get_config_section("channels").items()},
        "categories": {str(k): str(v) for k, v in get_config_section("categories").items()},
        "forums": {str(k): str(v) for k, v in get_config_section("forums").items()},
        "voice_channels": {str(k): str(v) for k, v in get_config_section("voice_channels").items()},
    }


def dangerous_permission_labels() -> list[tuple[str, str]]:
    configured = CONFIG.get("dangerous_permissions")
    if isinstance(configured, dict):
        result = []
        for attr, label in configured.items():
            result.append((str(attr), str(label)))
        if result:
            return result

    return [
        ("administrator", "Administrator"),
        ("manage_guild", "Server verwalten"),
        ("manage_roles", "Rollen verwalten"),
        ("manage_channels", "Kanäle verwalten"),
        ("manage_webhooks", "Webhooks verwalten"),
        ("ban_members", "Mitglieder bannen"),
        ("kick_members", "Mitglieder kicken"),
        ("manage_messages", "Nachrichten verwalten"),
        ("moderate_members", "Mitglieder timeouten"),
    ]


def resolve_role_name(role_ref: str) -> str:
    roles = get_roles_config()
    return roles.get(role_ref, role_ref)


def resolve_resource_name(resource_ref: str, preferred_type: str | None = None) -> str:
    resources = get_resources_config()

    if preferred_type and resource_ref in resources.get(preferred_type, {}):
        return resources[preferred_type][resource_ref]

    for section in ["channels", "forums", "voice_channels", "categories"]:
        if resource_ref in resources.get(section, {}):
            return resources[section][resource_ref]

    return resource_ref


def find_role(guild: discord.Guild, role_name_or_ref: str) -> discord.Role | None:
    role_name = resolve_role_name(role_name_or_ref)
    expected = normalize_name(role_name)

    for role in guild.roles:
        if normalize_name(role.name) == expected:
            return role

    # Fallback: hilfreich, wenn z. B. "Stammgast" statt "🍻 Stammgast" angegeben wurde.
    for role in guild.roles:
        if expected and expected in normalize_name(role.name):
            return role

    return None


def find_channel_by_name(guild: discord.Guild, channel_name_or_ref: str, preferred_type: str | None = None):
    channel_name = resolve_resource_name(channel_name_or_ref, preferred_type)
    expected = normalize_name(channel_name)

    for channel in guild.channels:
        if isinstance(channel, discord.CategoryChannel):
            continue
        if normalize_name(channel.name) == expected:
            return channel

    # Fallback: erlaubt z. B. "arc-tracker" bei "🤖-arc-tracker".
    for channel in guild.channels:
        if isinstance(channel, discord.CategoryChannel):
            continue
        if expected and expected in normalize_name(channel.name):
            return channel

    return None


def find_category_by_name(guild: discord.Guild, category_name_or_ref: str) -> discord.CategoryChannel | None:
    category_name = resolve_resource_name(category_name_or_ref, "categories")
    expected = normalize_name(category_name)

    for category in guild.categories:
        if normalize_name(category.name) == expected:
            return category

    # Fallback: erlaubt z. B. "Hinterzimmer" bei "🔒 Hinterzimmer".
    for category in guild.categories:
        if expected and expected in normalize_name(category.name):
            return category

    return None


def yes_no(value: bool) -> str:
    return "JA" if value else "NEIN"


def status_icon(ok: bool) -> str:
    return "✅" if ok else "⚠️"


def line_check(ok: bool, text: str) -> str:
    return f"{status_icon(ok)} {text}"


def get_effective_role_perms(channel, role: discord.Role) -> discord.Permissions | None:
    if not hasattr(channel, "permissions_for"):
        return None

    try:
        return channel.permissions_for(role)
    except Exception:
        return None


def serialize_permissions(perms: discord.Permissions) -> dict[str, bool]:
    wanted = [
        "view_channel",
        "send_messages",
        "read_message_history",
        "use_application_commands",
        "attach_files",
        "embed_links",
        "connect",
        "speak",
        "administrator",
        "manage_guild",
        "manage_roles",
        "manage_channels",
        "manage_webhooks",
        "manage_messages",
        "kick_members",
        "ban_members",
        "moderate_members",
        "create_public_threads",
        "create_private_threads",
        "send_messages_in_threads",
    ]

    return {name: bool(getattr(perms, name, False)) for name in wanted}


def role_to_dict(role: discord.Role | None) -> dict[str, Any] | None:
    if role is None:
        return None

    return {
        "id": role.id,
        "name": role.name,
        "position": role.position,
        "permissions": serialize_permissions(role.permissions),
    }


def channel_to_dict(channel) -> dict[str, Any]:
    return {
        "id": channel.id,
        "name": channel.name,
        "type": str(channel.type),
        "category": channel.category.name if getattr(channel, "category", None) else None,
    }


def add_finding(findings: list[dict[str, Any]], ok: bool, text: str, section: str, severity: str = "warning") -> None:
    findings.append(
        {
            "ok": ok,
            "section": section,
            "severity": "ok" if ok else severity,
            "text": text,
        }
    )


def get_rule_permission(rule_type: str) -> tuple[str | None, bool | None, str]:
    """
    Gibt zurück: Permission-Attribut, erwarteter Bool, Anzeigename.
    """
    mapping = {
        "can_see_channel": ("view_channel", True, "sehen"),
        "cannot_see_channel": ("view_channel", False, "sehen"),
        "can_see_category": ("view_channel", True, "sehen"),
        "cannot_see_category": ("view_channel", False, "sehen"),
        "can_write_channel": ("send_messages", True, "schreiben"),
        "cannot_write_channel": ("send_messages", False, "schreiben"),
        "can_read_channel": ("read_message_history", True, "Verlauf lesen"),
        "cannot_read_channel": ("read_message_history", False, "Verlauf lesen"),
        "can_use_slash": ("use_application_commands", True, "Slash-Commands nutzen"),
        "cannot_use_slash": ("use_application_commands", False, "Slash-Commands nutzen"),
        "can_attach_files": ("attach_files", True, "Dateien anhängen"),
        "cannot_attach_files": ("attach_files", False, "Dateien anhängen"),
        "can_embed_links": ("embed_links", True, "Embeds senden"),
        "cannot_embed_links": ("embed_links", False, "Embeds senden"),
        "can_join_voice": ("connect", True, "Voice betreten"),
        "cannot_join_voice": ("connect", False, "Voice betreten"),
        "can_speak_voice": ("speak", True, "sprechen"),
        "cannot_speak_voice": ("speak", False, "sprechen"),
        "can_manage_messages": ("manage_messages", True, "Nachrichten verwalten"),
        "cannot_manage_messages": ("manage_messages", False, "Nachrichten verwalten"),
    }
    return mapping.get(rule_type, (None, None, rule_type))


def get_rule_targets(rule: dict[str, Any]) -> list[dict[str, str]]:
    """
    Normalisiert channel/forum/voice/category/resources in eine Zielliste.
    """
    targets: list[dict[str, str]] = []

    for key, preferred in [
        ("channel", "channels"),
        ("channels", "channels"),
        ("forum", "forums"),
        ("forums", "forums"),
        ("voice", "voice_channels"),
        ("voice_channels", "voice_channels"),
        ("category", "categories"),
        ("categories", "categories"),
    ]:
        for value in listify(rule.get(key)):
            targets.append({"name": str(value), "preferred_type": preferred})

    for value in listify(rule.get("resources")):
        targets.append({"name": str(value), "preferred_type": "channels"})

    return targets


def resolve_target(guild: discord.Guild, target: dict[str, str]):
    preferred_type = target.get("preferred_type")
    name = target["name"]

    if preferred_type == "categories":
        return find_category_by_name(guild, name)

    return find_channel_by_name(guild, name, preferred_type)


def rule_resource_label(target_obj) -> str:
    if isinstance(target_obj, discord.CategoryChannel):
        return f"Kategorie {target_obj.name}"
    return f"#{target_obj.name}"


def check_dangerous_global_role(role: discord.Role) -> list[str]:
    return [label for attr, label in dangerous_permission_labels() if getattr(role.permissions, attr, False)]


def evaluate_config_rules(guild: discord.Guild, findings: list[dict[str, Any]]) -> None:
    rules = CONFIG.get("rules", [])
    if not isinstance(rules, list):
        add_finding(findings, False, "rules in config/audit.yaml muss eine Liste sein", "Config")
        return

    for index, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            add_finding(findings, False, f"Regel #{index} ist kein Objekt", "Config")
            continue

        if rule.get("enabled", True) is False:
            continue

        section = str(rule.get("section", "Config-Regeln"))
        name = str(rule.get("name", f"Regel #{index}"))
        rule_type = str(rule.get("type", "")).strip()

        roles = listify(rule.get("role")) + listify(rule.get("roles"))
        if not roles:
            add_finding(findings, False, f"{name}: Keine Rolle angegeben", section)
            continue

        # Sonderregel: globale kritische Rechte verbieten.
        if rule_type == "no_global_dangerous_permissions":
            for role_ref in roles:
                role = find_role(guild, str(role_ref))
                if role is None:
                    add_finding(findings, False, f"{name}: Rolle nicht gefunden: {resolve_role_name(str(role_ref))}", section)
                    continue

                hits = check_dangerous_global_role(role)
                add_finding(
                    findings,
                    not hits,
                    f"{name}: {role.name} hat keine global kritischen Rechte" if not hits else f"{name}: {role.name} hat kritische globale Rechte: {', '.join(hits)}",
                    section,
                )
            continue

        permission_attr, expected, permission_label = get_rule_permission(rule_type)
        if permission_attr is None or expected is None:
            add_finding(findings, False, f"{name}: Unbekannter Regeltyp: {rule_type}", section)
            continue

        targets = get_rule_targets(rule)
        if not targets:
            add_finding(findings, False, f"{name}: Kein Channel/Forum/Voice/Kategorie angegeben", section)
            continue

        for role_ref in roles:
            role = find_role(guild, str(role_ref))
            if role is None:
                add_finding(findings, False, f"{name}: Rolle nicht gefunden: {resolve_role_name(str(role_ref))}", section)
                continue

            for target in targets:
                target_obj = resolve_target(guild, target)
                if target_obj is None:
                    configured_name = resolve_resource_name(target["name"], target.get("preferred_type"))
                    add_finding(findings, False, f"{name}: Ziel nicht gefunden: {configured_name}", section)
                    continue

                perms = get_effective_role_perms(target_obj, role)
                if perms is None:
                    add_finding(findings, False, f"{name}: Rechte für {role.name} auf {rule_resource_label(target_obj)} konnten nicht gelesen werden", section)
                    continue

                actual = bool(getattr(perms, permission_attr, False))
                ok = actual == expected
                expected_text = "JA" if expected else "NEIN"
                add_finding(
                    findings,
                    ok,
                    f"{name}: {role.name} / {rule_resource_label(target_obj)} / {permission_label}={yes_no(actual)} erwartet={expected_text}",
                    section,
                )


# ------------------------------------------------------------
# Audit-Daten bauen
# ------------------------------------------------------------
async def build_audit_data(guild: discord.Guild) -> dict[str, Any]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    roles_config = get_roles_config()
    resources_config = get_resources_config()

    target_roles = {key: find_role(guild, key) for key in roles_config.keys()}

    dangerous_roles: list[dict[str, Any]] = []

    for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
        if role.name == "@everyone":
            continue

        hits = check_dangerous_global_role(role)
        if hits:
            dangerous_roles.append(
                {
                    "role": role_to_dict(role),
                    "permissions": hits,
                }
            )

    # Welche Rollen im großen Rechteblock ausgegeben werden sollen.
    role_audit_keys = CONFIG.get("role_audit")
    if not isinstance(role_audit_keys, list) or not role_audit_keys:
        role_audit_keys = list(roles_config.keys())

    roles_to_check: list[discord.Role] = []
    seen_role_ids: set[int] = set()

    for role_ref in role_audit_keys:
        role = find_role(guild, str(role_ref))
        if role and role.id not in seen_role_ids:
            roles_to_check.append(role)
            seen_role_ids.add(role.id)

    effective_permissions: list[dict[str, Any]] = []

    for channel in guild.channels:
        if isinstance(channel, discord.CategoryChannel):
            continue

        if not hasattr(channel, "permissions_for"):
            continue

        channel_entry = {
            "channel": channel_to_dict(channel),
            "roles": [],
        }

        for role in roles_to_check:
            perms = get_effective_role_perms(channel, role)
            if not perms:
                continue

            channel_entry["roles"].append(
                {
                    "role": role_to_dict(role),
                    "permissions": serialize_permissions(perms),
                }
            )

        effective_permissions.append(channel_entry)

    findings: list[dict[str, Any]] = []

    # Rollen-Fund aus config/audit.yaml.
    for key, expected_name in roles_config.items():
        role = target_roles.get(key)
        add_finding(
            findings,
            role is not None,
            f"Rolle {role.name if role else expected_name} gefunden" if role else f"Rolle nicht gefunden: {expected_name}",
            "Rollen-Check",
        )

    # Gefährliche globale Rechte.
    allowed_dangerous_global_roles = [resolve_role_name(str(item)) for item in listify(CONFIG.get("allowed_dangerous_global_roles"))]

    for entry in dangerous_roles:
        role_name = entry["role"]["name"]
        hits = ", ".join(entry["permissions"])
        if role_name in allowed_dangerous_global_roles:
            add_finding(findings, True, f"{role_name} hat erlaubte globale Rechte: {hits}", "Globale Rechte")
        else:
            add_finding(findings, False, f"{role_name} hat gefährliche globale Rechte: {hits}", "Globale Rechte")

    if not dangerous_roles:
        add_finding(findings, True, "Keine gefährlichen globalen Rollenrechte gefunden", "Globale Rechte")

    # Regeln aus config/audit.yaml.
    evaluate_config_rules(guild, findings)

    # Audit-Bot Selbstcheck.
    me = guild.me
    bot_selfcheck: dict[str, Any] = {"available": me is not None}

    compare_role_ref = CONFIG.get("audit_bot_compare_role", "stammgast")
    compare_role = find_role(guild, str(compare_role_ref))

    if me:
        bot_selfcheck = {
            "available": True,
            "name": me.display_name,
            "top_role": role_to_dict(me.top_role),
            "compare_role": role_to_dict(compare_role),
            "resource_permissions": [],
        }

        if compare_role:
            bot_above_compare = me.top_role.position > compare_role.position
            bot_same_as_compare = me.top_role.position == compare_role.position

            if bot_above_compare:
                add_finding(
                    findings,
                    False,
                    f"Audit-Bot-Rolle steht über {compare_role.name}: Bot={me.top_role.position}, Vergleich={compare_role.position}",
                    "Audit-Bot Selbstcheck",
                )
            elif bot_same_as_compare:
                add_finding(
                    findings,
                    True,
                    f"Audit-Bot-Rolle steht auf gleicher Position wie {compare_role.name}: Bot={me.top_role.position}, Vergleich={compare_role.position}",
                    "Audit-Bot Selbstcheck",
                )
            else:
                add_finding(
                    findings,
                    True,
                    f"Audit-Bot-Rolle steht unter {compare_role.name}: Bot={me.top_role.position}, Vergleich={compare_role.position}",
                    "Audit-Bot Selbstcheck",
                )

        for resource_ref in listify(CONFIG.get("audit_bot_permission_details")):
            target = {"name": str(resource_ref), "preferred_type": "channels"}
            target_obj = resolve_target(guild, target)
            if target_obj:
                p = target_obj.permissions_for(me)
                bot_selfcheck["resource_permissions"].append(
                    {
                        "resource": channel_to_dict(target_obj),
                        "permissions": serialize_permissions(p),
                    }
                )
    else:
        add_finding(findings, False, "Bot-Member konnte nicht gelesen werden. Prüfe Server Members Intent.", "Audit-Bot Selbstcheck")

    # Spezial-Details aus config/audit.yaml.
    special_resources = []
    for section_name, resources in resources_config.items():
        for key, configured_name in resources.items():
            if section_name == "categories":
                obj = find_category_by_name(guild, key)
            else:
                obj = find_channel_by_name(guild, key, section_name)

            special_resources.append(
                {
                    "key": key,
                    "configured_name": configured_name,
                    "section": section_name,
                    "found": channel_to_dict(obj) if obj and not isinstance(obj, discord.CategoryChannel) else ({"id": obj.id, "name": obj.name, "type": "category"} if obj else None),
                }
            )

    return {
        "generated_at": now,
        "guild": {
            "id": guild.id,
            "name": guild.name,
            "member_count": guild.member_count,
        },
        "configured_names": {
            "roles": roles_config,
            "resources": resources_config,
            "config_file": str(Path(CONFIG_FILE)),
        },
        "roles": {
            "target_roles": {key: role_to_dict(value) for key, value in target_roles.items()},
            "all_roles": [role_to_dict(role) for role in sorted(guild.roles, key=lambda r: r.position, reverse=True)],
            "dangerous_roles": dangerous_roles,
        },
        "channels": {
            "categories": [
                {
                    "id": category.id,
                    "name": category.name,
                    "channels": [channel_to_dict(channel) for channel in category.channels],
                }
                for category in guild.categories
            ],
            "uncategorized": [
                channel_to_dict(channel)
                for channel in guild.channels
                if getattr(channel, "category", None) is None and not isinstance(channel, discord.CategoryChannel)
            ],
        },
        "effective_permissions": effective_permissions,
        "special": {
            "resources": special_resources,
            "bot_selfcheck": bot_selfcheck,
        },
        "findings": findings,
    }


# ------------------------------------------------------------
# TXT-Bericht bauen
# ------------------------------------------------------------
def build_txt_report(data: dict[str, Any]) -> str:
    lines: list[str] = []

    guild = data["guild"]
    roles = data["roles"]
    channels = data["channels"]
    special = data["special"]
    findings = data["findings"]

    warning_count = sum(1 for item in findings if not item["ok"])

    lines.append("========================================")
    lines.append("DISCORD SERVER AUDIT")
    lines.append("========================================")
    lines.append(f"Server: {guild['name']}")
    lines.append(f"Server-ID: {guild['id']}")
    lines.append(f"Mitglieder: {guild['member_count']}")
    lines.append(f"Erstellt am: {data['generated_at']}")
    lines.append(f"Config: {data['configured_names']['config_file']}")
    lines.append(f"Warnungen: {warning_count}")
    lines.append("")

    # ------------------------------------------------------------
    # Rollen finden
    # ------------------------------------------------------------
    lines.append("ROLLEN-CHECK")
    lines.append("----------------------------------------")

    target_roles = roles["target_roles"]
    roles_config = data["configured_names"]["roles"]

    for key, expected_name in roles_config.items():
        role = target_roles.get(key)
        if role:
            lines.append(f"✅ Rolle gefunden: {role['name']} | Key: {key} | Position: {role['position']}")
        else:
            lines.append(f"⚠️ Rolle NICHT gefunden: {expected_name} | Key: {key}")

    lines.append("")

    # ------------------------------------------------------------
    # Rollen-Reihenfolge
    # ------------------------------------------------------------
    lines.append("ROLLEN-REIHENFOLGE")
    lines.append("----------------------------------------")

    for role in roles["all_roles"]:
        lines.append(f"{role['position']:>3} | {role['name']}")

    lines.append("")

    # ------------------------------------------------------------
    # Gefährliche globale Rechte
    # ------------------------------------------------------------
    lines.append("GEFÄHRLICHE GLOBALE ROLLENRECHTE")
    lines.append("----------------------------------------")

    if roles["dangerous_roles"]:
        for entry in roles["dangerous_roles"]:
            lines.append(f"⚠️ {entry['role']['name']}: {', '.join(entry['permissions'])}")
    else:
        lines.append("✅ Keine gefährlichen globalen Rollenrechte gefunden.")

    lines.append("")
    lines.append("Hinweis:")
    lines.append("Welche globalen Rechte als okay gelten, steuerst du in config/audit.yaml über allowed_dangerous_global_roles.")
    lines.append("")

    # ------------------------------------------------------------
    # Konkrete Soll-Regeln
    # ------------------------------------------------------------
    lines.append("SOLL-REGELN UND BEFUNDE")
    lines.append("----------------------------------------")

    if findings:
        current_section = None
        for item in findings:
            if item["section"] != current_section:
                current_section = item["section"]
                lines.append("")
                lines.append(f"[{current_section}]")
            lines.append(line_check(item["ok"], item["text"]))
    else:
        lines.append("✅ Keine Befunde vorhanden.")

    lines.append("")

    # ------------------------------------------------------------
    # Kategorien und Channels
    # ------------------------------------------------------------
    lines.append("KATEGORIEN UND CHANNELS")
    lines.append("----------------------------------------")

    if channels["categories"]:
        for category in channels["categories"]:
            lines.append(f"📁 {category['name']}")
            for channel in category["channels"]:
                lines.append(f"  - #{channel['name']} ({channel['type']})")
    else:
        lines.append("Keine Kategorien gefunden.")

    lines.append("")
    lines.append("CHANNELS OHNE KATEGORIE")
    lines.append("----------------------------------------")

    if channels["uncategorized"]:
        for channel in channels["uncategorized"]:
            lines.append(f"- #{channel['name']} ({channel['type']})")
    else:
        lines.append("Keine Channels ohne Kategorie gefunden.")

    lines.append("")

    # ------------------------------------------------------------
    # Effektive Rechte pro Zielrolle und Channel
    # ------------------------------------------------------------
    lines.append("EFFEKTIVE CHANNEL-RECHTE PRO ROLLE")
    lines.append("----------------------------------------")

    for entry in data["effective_permissions"]:
        channel = entry["channel"]
        lines.append(f"#{channel['name']} ({channel['type']})")

        for role_entry in entry["roles"]:
            role = role_entry["role"]
            p = role_entry["permissions"]
            lines.append(
                f"  {role['name']}: "
                f"sehen={yes_no(p['view_channel'])}, "
                f"schreiben={yes_no(p['send_messages'])}, "
                f"verlauf={yes_no(p['read_message_history'])}, "
                f"slash={yes_no(p['use_application_commands'])}, "
                f"dateien={yes_no(p['attach_files'])}, "
                f"embeds={yes_no(p['embed_links'])}, "
                f"voice={yes_no(p['connect'])}, "
                f"sprechen={yes_no(p['speak'])}, "
                f"manage_messages={yes_no(p['manage_messages'])}"
            )

        lines.append("")

    # ------------------------------------------------------------
    # Spezialchecks als Detailblock
    # ------------------------------------------------------------
    lines.append("SPEZIALCHECKS")
    lines.append("----------------------------------------")

    for resource in special.get("resources", []):
        found = resource.get("found")
        if found:
            prefix = "Kategorie" if resource["section"] == "categories" else "#"
            if prefix == "Kategorie":
                lines.append(f"✅ {resource['key']} gefunden: {found['name']} ({resource['section']})")
            else:
                lines.append(f"✅ {resource['key']} gefunden: #{found['name']} ({resource['section']})")
        else:
            lines.append(f"⚠️ {resource['key']} nicht gefunden: {resource['configured_name']} ({resource['section']})")

    lines.append("")

    # ------------------------------------------------------------
    # Audit-Bot Selbstcheck
    # ------------------------------------------------------------
    lines.append("AUDIT-BOT SELBSTCHECK")
    lines.append("----------------------------------------")

    selfcheck = special["bot_selfcheck"]

    if selfcheck.get("available"):
        top_role = selfcheck["top_role"]
        compare_role = selfcheck.get("compare_role")
        lines.append(f"Bot-Name: {selfcheck['name']}")
        lines.append(f"Höchste Bot-Rolle: {top_role['name']} | Position: {top_role['position']}")

        if compare_role:
            lines.append(f"Vergleichsrolle: {compare_role['name']} | Position: {compare_role['position']}")

            if top_role["position"] > compare_role["position"]:
                lines.append(f"⚠️ Audit-Bot-Rolle steht über {compare_role['name']}")
            elif top_role["position"] == compare_role["position"]:
                lines.append(f"ℹ️ Audit-Bot-Rolle steht auf gleicher Position wie {compare_role['name']}")
            else:
                lines.append(f"✅ Audit-Bot-Rolle steht unter {compare_role['name']}")
        else:
            lines.append("⚠️ Vergleichsrolle wurde nicht gefunden. Rollenvergleich nicht möglich.")

        for detail in selfcheck.get("resource_permissions", []):
            resource = detail["resource"]
            p = detail["permissions"]
            lines.append(f"Audit-Bot im #{resource['name']}:")
            lines.append(f"  - sehen: {yes_no(p['view_channel'])}")
            lines.append(f"  - schreiben: {yes_no(p['send_messages'])}")
            lines.append(f"  - Nachrichtenverlauf: {yes_no(p['read_message_history'])}")
            lines.append(f"  - Embeds: {yes_no(p['embed_links'])}")
            lines.append(f"  - Dateien: {yes_no(p['attach_files'])}")
            lines.append(f"  - Slash-Commands: {yes_no(p['use_application_commands'])}")
    else:
        lines.append("⚠️ Bot-Member konnte nicht gelesen werden. Prüfe Server Members Intent.")

    lines.append("")

    # ------------------------------------------------------------
    # Kurzfazit
    # ------------------------------------------------------------
    lines.append("KURZFAZIT")
    lines.append("----------------------------------------")

    if warning_count == 0:
        lines.append("✅ Keine Warnungen gefunden.")
    else:
        lines.append(f"⚠️ {warning_count} Warnung(en) gefunden. Prüfe zuerst den Block 'SOLL-REGELN UND BEFUNDE'.")

    lines.append("")
    lines.append("Wichtige Zielwerte kommen jetzt aus config/audit.yaml.")
    lines.append("Wenn du Rollen, Channels oder Regeln änderst, bearbeite die passende Datei unter config/ und führe danach /admin reload aus.")

    return "\n".join(lines)


def safe_file_stem(value: str) -> str:
    return "".join(c for c in value if c.isalnum() or c in "-_ ").strip().replace(" ", "_") or "discord_server"




class AuditCog(commands.Cog):
    audit_group = app_commands.Group(name="audit", description="Server-Rechte und Soll-Regeln prüfen")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @audit_group.command(name="run", description="Erstellt einen Rechte-Audit dieses Discord-Servers.")
    @app_commands.describe(format="Ausgabeformat: txt, json oder both")
    @app_commands.choices(format=[
        app_commands.Choice(name="TXT", value="txt"),
        app_commands.Choice(name="JSON", value="json"),
        app_commands.Choice(name="TXT + JSON", value="both"),
    ])
    @admin_only()
    async def audit_run(self, interaction: discord.Interaction, format: str = "txt"):
        if interaction.guild is None:
            await interaction.response.send_message("Dieser Befehl funktioniert nur auf einem Server.", ephemeral=True)
            return
        set_config(self.bot.config_data)
        await interaction.response.defer(ephemeral=True, thinking=True)

        data = await build_audit_data(interaction.guild)
        report = build_txt_report(data)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_guild_name = safe_file_stem(interaction.guild.name)
        txt_path = REPORT_DIR / f"audit_{safe_guild_name}_{timestamp}.txt"
        json_path = REPORT_DIR / f"audit_{safe_guild_name}_{timestamp}.json"
        files: list[discord.File] = []
        if format in ("txt", "both"):
            txt_path.write_text(report, encoding="utf-8")
            files.append(discord.File(txt_path))
        if format in ("json", "both"):
            json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            files.append(discord.File(json_path))
        warning_count = sum(1 for item in data["findings"] if not item["ok"])
        await interaction.followup.send(
            content=f"Audit fertig. Warnungen: {warning_count}. Prüfe zuerst 'SOLL-REGELN UND BEFUNDE'.",
            files=files,
            ephemeral=True,
        )

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        handled = await handle_app_command_error(interaction, error)
        if handled:
            return
        raise error


async def setup(bot: commands.Bot):
    set_config(bot.config_data)
    await bot.add_cog(AuditCog(bot))
