from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
MAIN_CONFIG_FILE = CONFIG_DIR / "main.yaml"


def deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Mergt YAML-Config-Dateien rekursiv, ohne das Original zu verändern."""
    result = dict(base)
    for key, value in extra.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config-Datei nicht gefunden: {path}")
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} muss ein YAML-Objekt enthalten.")
    return data


def load_config() -> dict[str, Any]:
    """
    Lädt config/main.yaml und alle dort verlinkten Modul-Configs.

    Wichtig:
    - main.yaml entscheidet, welche Cogs geladen werden.
    - Die Modul-Configs enthalten nur Detail-Einstellungen.
    - Für bestehenden Cog-Code wird alles wieder zu einer config_data zusammengeführt.
    """
    main_config = read_yaml(MAIN_CONFIG_FILE)
    merged = dict(main_config)

    modules = main_config.get("modules", {})
    if not isinstance(modules, dict):
        raise ValueError("config/main.yaml -> modules muss ein YAML-Objekt sein.")

    for module_name, module_cfg in modules.items():
        if not isinstance(module_cfg, dict):
            logging.warning("Modul '%s' in main.yaml ist ungültig und wird übersprungen.", module_name)
            continue

        config_path = module_cfg.get("config")
        if not config_path:
            continue

        path = BASE_DIR / str(config_path)
        module_data = read_yaml(path)
        merged = deep_merge(merged, module_data)

    return merged


def get_enabled_cogs(config: dict[str, Any]) -> list[str]:
    modules = config.get("modules", {})
    if not isinstance(modules, dict):
        return ["cogs.admin"]

    cogs: list[str] = []
    for module_name, module_cfg in modules.items():
        if not isinstance(module_cfg, dict):
            continue
        enabled = bool(module_cfg.get("enabled", False))
        cog = module_cfg.get("cog")
        if enabled and cog:
            cogs.append(str(cog))

    if "cogs.admin" not in cogs:
        cogs.insert(0, "cogs.admin")

    return cogs
