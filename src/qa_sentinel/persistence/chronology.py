"""SQLite ordering of ISO timestamps by UTC instant, including microseconds."""
from datetime import datetime, timezone


def utc_microseconds(value: str) -> int:
    stamp = datetime.fromisoformat(value)
    # Historical naive timestamps are interpreted as UTC, never local time.
    stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
    delta = stamp - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
