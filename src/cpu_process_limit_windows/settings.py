from __future__ import annotations

from dataclasses import dataclass


MIN_CPU_PERCENT = 0.01
MAX_CPU_PERCENT = 100.0
DEFAULT_CPU_PERCENT = 25.0
DEFAULT_WINDOW_WIDTH = 1120
DEFAULT_WINDOW_HEIGHT = 680
POLL_INTERVAL_MS = 1000
PROCESS_REFRESH_INTERVAL_MS = 1000


@dataclass(frozen=True)
class AppSettings:
    min_cpu_percent: float = MIN_CPU_PERCENT
    max_cpu_percent: float = MAX_CPU_PERCENT
    default_cpu_percent: float = DEFAULT_CPU_PERCENT
    window_width: int = DEFAULT_WINDOW_WIDTH
    window_height: int = DEFAULT_WINDOW_HEIGHT
    poll_interval_ms: int = POLL_INTERVAL_MS
    process_refresh_interval_ms: int = PROCESS_REFRESH_INTERVAL_MS


SETTINGS = AppSettings()


def parse_cpu_percent(value: str) -> float:
    try:
        percent = float(value)
    except ValueError as exc:
        raise ValueError("CPU percent must be a number.") from exc

    if not MIN_CPU_PERCENT <= percent <= MAX_CPU_PERCENT:
        raise ValueError(
            f"CPU percent must be between {MIN_CPU_PERCENT:g} and {MAX_CPU_PERCENT:g}."
        )
    return percent
