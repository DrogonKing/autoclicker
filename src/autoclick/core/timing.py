"""
Timing: when does the next click happen?

The whole point of this module is that it never accumulates drift.

The naive autoclicker loop is:

    while running:
        click()
        sleep(interval)

which is wrong in a way that only shows up after a while. Each iteration costs the sleep PLUS the
time the click itself took, so a 100 ms interval on a machine where clicking costs 3 ms actually
fires every 103 ms. After 1000 clicks you are 3 seconds late, and after an hour the last click is
minutes away from where the user asked for it.

This module computes absolute deadlines instead: the deadline for click N is simply
`start + N * interval`, so click 10,000 lands where it should no matter how slow any individual
click was. If the machine falls far enough behind that it cannot catch up, that is reported rather
than hidden - see `missed`.
"""

from __future__ import annotations

from dataclasses import dataclass

# If a deadline is this far in the past, we are too far behind to pretend it still happened on time.
# Reported as a missed tick and skipped, rather than firing a machine-gun burst to catch up.
LATE_TOLERANCE_MS = 250


def deadline_for(index: int, interval_ms: int, start_ms: int) -> int:
    """Absolute time of tick `index` (0-based), in the same clock as `start_ms`."""
    return start_ms + index * interval_ms


@dataclass
class TickDecision:
    """What to do about one tick."""

    sleep_ms: int
    missed: bool = False
    # how late we were, for the missed case
    late_by_ms: int = 0


def next_tick(index: int, interval_ms: int, start_ms: int, now_ms: int) -> TickDecision:
    """
    How long to sleep before ticking `index`, and whether we are hopelessly behind.

    `now_ms` is "now" on the same clock as `start_ms`. A positive sleep means wait; zero means fire
    now. The caller is expected to fire immediately when sleep_ms is 0, because the deadline has
    already arrived (or nearly has).
    """
    due = deadline_for(index, interval_ms, start_ms)
    delta = due - now_ms
    if delta >= 0:
        return TickDecision(sleep_ms=delta)
    late = -delta
    if late > LATE_TOLERANCE_MS:
        return TickDecision(sleep_ms=0, missed=True, late_by_ms=late)
    # merely early by a hair: fine, the caller fires now
    return TickDecision(sleep_ms=0)


def interval_from_hz(hz: float) -> int:
    """
    Clicks per second to an interval in ms.

    A UI offers "per second" because it is how people describe fast clicking; the engine works in ms.
    Values above 1000/second have no meaning because ms granularity cannot express them, so they are
    rejected rather than silently rounded to 1 ms.
    """
    if hz <= 0:
        raise ValueError("rate must be greater than 0")
    if hz > 1000:
        raise ValueError("above 1000/second the millisecond timer cannot express the interval")
    return int(round(1000.0 / hz))


def ms_until_clock(hms: str, now: tuple[int, int, int], *, only_future: bool = True) -> int:
    """
    Milliseconds from the wall clock `now` (h, m, s) until `hms`.

    If the target time has already passed today, it is treated as tomorrow - a user typing 11:50 when
    it is 11:51 means the next 11:50, not a negative delay. `only_future=False` allows a negative
    result, which is useful for tests that want to see the raw difference.
    """
    from .model import parse_clock

    th, tm, ts = parse_clock(hms)
    nh, nm, ns = now
    target = (th * 3600) + (tm * 60) + ts
    current = (nh * 3600) + (nm * 60) + ns
    diff = target - current
    if diff < 0 and only_future:
        diff += 24 * 3600
    return diff * 1000


def clock_from_ms_of_day(ms_of_day: int) -> str:
    """
    Milliseconds since local midnight to "HH:MM:SS".

    Used to tell the user what a relative delay worked out to. The inverse of ms_until_clock for the
    same day, and it wraps rather than producing a 24+ hour clock.
    """
    if ms_of_day < 0:
        raise ValueError("ms_of_day cannot be negative")
    total = (ms_of_day // 1000) % (24 * 3600)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
