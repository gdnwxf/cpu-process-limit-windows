from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cpu_process_limit_windows.settings import SETTINGS, parse_cpu_percent


CONFIG_PATH = Path.home() / ".cpu_limit" / "config.json"


@dataclass
class UserConfig:
    default_cpu_percent: float = SETTINGS.default_cpu_percent
    process_limits: dict[str, float] = field(default_factory=dict)


def process_config_key(name: str, path: str) -> str:
    value = path.strip() or name.strip()
    return value.lower()


def load_config() -> UserConfig:
    if not CONFIG_PATH.exists():
        return UserConfig()

    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return UserConfig()

    if not isinstance(raw, dict):
        return UserConfig()

    config = UserConfig()
    default_value = raw.get("default_cpu_percent", SETTINGS.default_cpu_percent)
    try:
        config.default_cpu_percent = parse_cpu_percent(str(default_value))
    except ValueError:
        config.default_cpu_percent = SETTINGS.default_cpu_percent

    process_limits = raw.get("process_limits", {})
    if isinstance(process_limits, dict):
        config.process_limits = _load_process_limits(process_limits)

    return config


def save_config(config: UserConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "default_cpu_percent": config.default_cpu_percent,
        "process_limits": dict(sorted(config.process_limits.items())),
    }
    temp_path = CONFIG_PATH.with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(CONFIG_PATH)


def _load_process_limits(values: dict[str, Any]) -> dict[str, float]:
    process_limits: dict[str, float] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not key.strip():
            continue
        try:
            process_limits[key.lower()] = parse_cpu_percent(str(value))
        except ValueError:
            continue
    return process_limits
