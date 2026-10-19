"""US equity session dates via exchange_calendars (XNYS): weekends and NYSE holidays are skipped."""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache

from .models import TORONTO


@lru_cache(maxsize=1)
def _cal():
    import exchange_calendars as xc

    return xc.get_calendar("XNYS")


def is_session(d: date) -> bool:
    return _cal().is_session(d.isoformat())


def session_on_or_after(d: date) -> date:
    return _cal().date_to_session(d.isoformat(), direction="next").date()


def previous_session(d: date) -> date:
    """Last session strictly before d."""
    return _cal().date_to_session(d.isoformat(), direction="previous").date() if not is_session(d) \
        else _cal().previous_session(d.isoformat()).date()


def sessions_between(start: date, end: date) -> list[date]:
    return [ts.date() for ts in _cal().sessions_in_range(start.isoformat(), end.isoformat())]


def resolve_target(spec: str, now: datetime | None = None) -> date:
    """'next' -> the next session to trade. Evening/weekend runs point at the next session;
    running before the open on a session day points at today. 'YYYY-MM-DD' -> that session (or next)."""
    if spec != "next":
        return session_on_or_after(date.fromisoformat(spec))
    now = (now or datetime.now(TORONTO)).astimezone(TORONTO)
    today = now.date()
    if is_session(today) and now.hour < 9:
        return today
    return session_on_or_after(date.fromordinal(today.toordinal() + 1))
