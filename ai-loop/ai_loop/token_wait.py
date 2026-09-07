"""Detection and scheduling for CLI token/quota replenishment waits."""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Callable


TOKEN_LIMIT_PATTERNS = (
    "usage limit",
    "token limit",
    "rate limit",
    "rate-limit",
    "quota exceeded",
    "quota exhausted",
    "out of tokens",
    "too many requests",
)


def is_token_limit(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in TOKEN_LIMIT_PATTERNS)


def replenishment_time(
    text: str,
    *,
    now: datetime | None = None,
) -> datetime | None:
    """Extract the next usable instant, including the requested one-minute pad."""

    if not is_token_limit(text):
        return None
    current = now or datetime.now().astimezone()

    iso_matches = re.findall(
        r"\b(20\d{2}-\d{2}-\d{2}[T ][0-2]\d:[0-5]\d(?::[0-5]\d)?(?:Z|[+-]\d{2}:?\d{2})?)\b",
        text,
    )
    for raw in iso_matches:
        normalized = raw.replace(" ", "T")
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=current.tzinfo)
        if parsed > current:
            return parsed.astimezone(timezone.utc) + timedelta(minutes=1)

    duration = re.search(
        r"(?:try again|resets?|replenish(?:ed)?|available)\s+in\s+"
        r"(?:(\d+)\s*(?:hours?|hrs?|h))?\s*"
        r"(?:(\d+)\s*(?:minutes?|mins?|m))?\s*"
        r"(?:(\d+)\s*(?:seconds?|secs?|s))?",
        text,
        flags=re.IGNORECASE,
    )
    if duration and any(duration.groups()):
        hours, minutes, seconds = (int(value or 0) for value in duration.groups())
        return (current + timedelta(hours=hours, minutes=minutes, seconds=seconds + 60)).astimezone(
            timezone.utc
        )

    clock = re.search(
        r"(?:resets?|replenish(?:ed)?|available|try again)(?:\s+at)?\s+"
        r"([01]?\d|2[0-3])(?::([0-5]\d))?\s*(am|pm)?"
        r"(?:\s+([A-Z]{2,5}|[+-]\d{2}:?\d{2}))?",
        text,
        flags=re.IGNORECASE,
    )
    if clock:
        hour = int(clock.group(1))
        minute = int(clock.group(2) or 0)
        meridiem = (clock.group(3) or "").lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= current:
            candidate += timedelta(days=1)
        return (candidate + timedelta(minutes=1)).astimezone(timezone.utc)
    return None


def wait_until(
    target: datetime,
    *,
    on_tick: Callable[[int], None] | None = None,
) -> None:
    """Wait in short intervals so logs and state can remain informative."""

    while True:
        remaining = max(
            0,
            round((target - datetime.now(timezone.utc)).total_seconds()),
        )
        if on_tick is not None:
            on_tick(remaining)
        if remaining <= 0:
            return
        time.sleep(min(60, remaining))
