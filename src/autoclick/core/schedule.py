"""
Schedules: how long to wait before each repetition.

Two behaviours were asked for, and they are genuinely different, so they get two named classes rather
than a flag threaded through the loop:

  - FixedInterval "every 500 ms": each tick is 500 ms after the previous one, measured from the
    START, so it never drifts.
  - BackToBack "as fast as possible": no waiting at all beyond an optional floor. This is the
    "spam clicks" mode, and the floor exists because a 0 ms interval on a real machine pegs a CPU
    core doing nothing but waiting for the OS.

`schedule_for()` is the single place a profile becomes timing, so the simple four-field mode
and the advanced step sequence cannot develop different ideas about what an interval means.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .errors import ParseError
from .errors import ParseError
from .model import Profile

# No floor by default: the user asked for control, and a hidden minimum would make "0 ms" a lie.
# The UI shows the achieved rate instead, which is honest.
DEFAULT_FLOOR_MS = 0


class Schedule(Protocol):
    def interval_ms(self, index: int) -> int | None: ...
    def wait_before(self, index: int, elapsed_ms: int) -> int: ...
    def is_done(self, index: int, elapsed_ms: int) -> bool: ...


@dataclass
class FixedInterval:
    """`interval` ms between the starts of consecutive repetitions."""

    interval: int

    def interval_ms(self, index: int) -> int | None:
        return self.interval

    def wait_before(self, index: int, elapsed_ms: int) -> int:
        if index == 0:
            return 0
        return max(0, index * self.interval - elapsed_ms)

    def is_done(self, index: int, elapsed_ms: int) -> bool:
        return False

    @staticmethod
    def for_profile(profile: Profile) -> "FixedInterval":
        return FixedInterval(interval=profile.interval_ms)


@dataclass
class BackToBack:
    """
    No interval: repeat as soon as the previous repetition finished.

    `floor_ms` is the only brake. Zero means genuinely unbounded, which is what "as fast as possible"
    means - and the achieved rate is reported so the user can see what their machine managed.
    """

    floor_ms: int = DEFAULT_FLOOR_MS

    def interval_ms(self, index: int) -> int | None:
        return self.floor_ms

    def wait_before(self, index: int, elapsed_ms: int) -> int:
        return 0

    def is_done(self, index: int, elapsed_ms: int) -> bool:
        return False

    @staticmethod
    def for_profile(profile: Profile) -> "BackToBack":
        return BackToBack(floor_ms=max(0, profile.interval_ms))


DURATION_RE = re.compile(
    r"^\s*(?:(?P<h>\d+)\s*h)?\s*(?:(?P<m>\d+)\s*m(?!s))?\s*(?:(?P<s>\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)?)?\s*$",
    re.IGNORECASE,
)


def parse_duration(text: str) -> int:
    """
    Parse a human duration into milliseconds.

    Accepts "500ms", "1.5s", "2m", "1h30m", "90", and plain numbers as milliseconds. A bare number is
    milliseconds because that is the unit the whole app is built on, and guessing seconds for "500"
    would turn a half-second pause into eight minutes.

    Raises ParseError so the UI can show the message next to the field.
    """
    raw = (text or "").strip().lower()
    if not raw:
        raise ParseError("duration is empty")

    # explicit millisecond form first: it must not fall through to the seconds branch
    if raw.endswith("ms"):
        num = raw[:-2].strip()
        try:
            return int(float(num))
        except ValueError:
            raise ParseError(f"'{num}' is not a number of milliseconds") from None

    if raw.isdigit():
        # a bare integer is milliseconds; anything with punctuation goes through the general form
        return int(raw)

    # plain number, possibly fractional, optionally suffixed
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)?", raw)
    if m:
        value = float(m.group(1))
        unit = (m.group(2) or "ms").lower()
        if unit.startswith("s"):
            return int(round(value * 1000))
        if unit.startswith("m"):
            return int(round(value * 60_000))
        if unit.startswith("h"):
            return int(round(value * 3_600_000))
        return int(round(value))

    # compound: 1h30m, 2m15s
    total = 0.0
    found = False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(h|m|s)", raw):
        found = True
        v = float(num)
        total += v * {"h": 3_600_000, "m": 60_000, "s": 1000}[unit]
    if found:
        return int(round(total))

    raise ParseError(f"cannot read '{text}' as a duration (try 500ms, 1.5s, 2m, 1h30m)")


def parse_start_time(text: str) -> tuple[str, int]:
    """
    Parse what the user typed into (clock_time, delay_ms).

    Returns exactly one of the two non-empty, so the caller never has to guess which the user meant:
      - "11:50:20"  -> ("11:50:20", 0)
      - "+2500"     -> ("", 2500)      a relative delay in ms
      - "2.5s"      -> ("", 2500)      the same thing in friendly units
      - ""          -> ("", 0)         start immediately
    """
    from .model import normalise_clock, parse_clock

    raw = (text or "").strip()
    if not raw:
        return "", 0  # immediate

    if raw.startswith("+"):
        return "", parse_duration(raw[1:])

    # a clock time has a colon and looks like 11:50
    if ":" in raw:
        # normalise first so a pasted "2026-01-02T11:50:20" is stored as "11:50:20": the profile must
        # contain a time of day, not whatever the user happened to paste
        normalised = normalise_clock(raw)
        parse_clock(normalised)  # raises a readable error if malformed
        return normalised, 0

    # otherwise a duration, but only if it parses as one; a bare "11" would be ambiguous, so it is
    # rejected rather than silently treated as 11 ms
    try:
        ms = parse_duration(raw)
    except ParseError:
        raise ParseError(
            f"cannot read '{text}' as a start time. Use HH:MM:SS for a clock time, or 500ms / 2s / "
            f"+1500 for a delay from now."
        ) from None
    return "", ms


def schedule_for(profile: Profile) -> Schedule:
    """
    The single place a profile becomes timing.

    An interval of 0 means "no waiting", which is a different schedule rather than a fast one: it
    skips the deadline arithmetic entirely, so a BackToBack run reports its achieved rate instead of
    an interval it was never holding to.
    """
    if profile.interval_ms > 0:
        return FixedInterval.for_profile(profile)
    return BackToBack.for_profile(profile)
