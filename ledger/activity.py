"""
Activity map for agent-ledger.
Identifies where user activity is concentrated in a time range.
Pure Python stdlib.
"""

from datetime import datetime, timedelta, timezone

_DAY = 24 * 60 * 60
_WEEK = 7 * _DAY


def bucket_size_minutes(range_seconds: int) -> int:
    """Return bucket granularity in minutes for a given range length in seconds."""
    if range_seconds >= _WEEK:
        return 1440  # daily
    if range_seconds >= _DAY:
        return 60    # hourly
    if range_seconds >= 60 * 60:
        return 15
    return 5
