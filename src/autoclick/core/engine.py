"""
The execution engine.

Rules it follows, each of which exists because the alternative is a bug users hit:

  - The clock is injected. `time_fn` and `sleep_fn` are parameters, so a test can run 10,000 clicks
    in 4 ms and assert exactly where each one landed. An engine that sleeps on the real clock can
    only be tested by waiting, which means it is not really tested.
  - Deadlines are absolute, so drift cannot accumulate (see core/timing.py).
  - Repeat counting is exact. "100 clicks" means exactly 100, not "until the stopwatch says done".
  - A stall is reported, not hidden. If the machine cannot keep up, the user is told; silently
    spraying a burst to catch up is how an autoclicker does something unexpected at 3am.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Protocol

from . import timing
from .errors import ParseError, ProfileError
from .model import ClickStep, KeyStep, Profile, Step, WaitStep
from .schedule import Schedule, parse_duration, parse_start_time, schedule_for


class InputBackend(Protocol):
    """
    What the engine needs from the platform.

    Kept to four calls so the Windows implementation is small enough to review, and so tests can
    supply a recorder instead.
    """

    def move(self, x: int, y: int) -> None: ...
    def click(self, button: str, double: bool = False) -> None: ...
    def key_down(self, key: str) -> None: ...
    def key_up(self, key: str) -> None: ...


@dataclass
class RunStats:
    """What actually happened. Shown in the UI so a run can be judged without trusting it."""

    started_at_ms: int = 0
    finished_at_ms: int = 0
    clicks_sent: int = 0
    keys_sent: int = 0
    repeats_done: int = 0
    missed_ticks: int = 0
    max_late_ms: int = 0
    error: str = ""
    stopped_by: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "clicks_sent": self.clicks_sent,
            "keys_sent": self.keys_sent,
            "repeats_done": self.repeats_done,
            "missed_ticks": self.missed_ticks,
            "max_late_ms": self.max_late_ms,
            "elapsed_ms": max(0, self.finished_at_ms - self.started_at_ms),
            "error": self.error,
            "stopped_by": self.stopped_by,
        }


class Engine:
    """
    Runs a profile until it finishes, or until `stop()` is called.

    Threaded on purpose: the UI must stay responsive so Stop works. The engine thread only ever calls
    the injected sleep and the backend, never Tk.
    """

    def __init__(
        self,
        backend: InputBackend,
        *,
        time_fn: Callable[[], int] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        now_clock: Callable[[], tuple[int, int, int]] | None = None,
    ) -> None:
        self._backend = backend
        self._time_fn = time_fn or (lambda: int(__import__("time").monotonic() * 1000))
        self._sleep_fn = sleep_fn or (lambda s: __import__("time").sleep(s / 1000.0))
        self._now_clock = now_clock or _local_clock

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.stats = RunStats()
        self._on_progress: Callable[[RunStats], None] | None = None

    # ------------------------------------------------------------------ control

    def on_progress(self, fn: Callable[[RunStats], None]) -> None:
        self._on_progress = fn

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self, reason: str = "stopped") -> None:
        self.stats.stopped_by = reason
        self._stop.set()

    def start(self, profile: Profile) -> RunStats:
        """Run in a background thread. Returns immediately; poll `stats` or use `on_progress`."""
        if self.is_running():
            raise ProfileError("already running")
        self.stats = RunStats(stopped_by="finished")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(profile,), name="autoclick-engine", daemon=True,
        )
        self._thread.start()
        return self.stats

    def run_blocking(self, profile: Profile) -> RunStats:
        """
        Run on the calling thread.

        This is what the tests use, and what a headless run would use. `start()` is a thin wrapper
        over it.
        """
        self.stats = RunStats(stopped_by="finished")
        self._stop.clear()
        self._run(profile)
        return self.stats

    # ------------------------------------------------------------------ the loop

    def _run(self, profile: Profile) -> None:
        try:
            profile.validate()
        except ProfileError as e:
            self.stats.error = str(e)
            self.stats.stopped_by = "invalid"
            return

        steps = profile.compile_steps()
        t0 = self._time_fn()
        self.stats.started_at_ms = t0

        # When does the first tick happen? An explicit clock time wins over a relative delay, because
        # a user who typed a time meant that time.
        if profile.start_at or profile.start_in_ms:
            if profile.start_at:
                delay_ms = timing.ms_until_clock(profile.start_at, self._now_clock())
            else:
                delay_ms = profile.start_in_ms
            if self._sleep_until(t0 + delay_ms, t0):
                self.stats.finished_at_ms = self._time_fn()
                return

        schedule = self._schedule_for(profile)

        index = 0
        start_ms = self._time_fn()
        deadline_ms = start_ms
        while not self._stop.is_set():
            now = self._time_fn()

            if profile.max_duration_ms and (now - start_ms) >= profile.max_duration_ms:
                self.stats.stopped_by = "max duration reached"
                break

            if profile.repeat and index >= profile.repeat:
                break
            if schedule.is_done(index, now - start_ms):
                break

            wait = schedule.wait_before(index, now - start_ms)
            if wait > 0 and self._sleep_until(now + wait, start_ms):
                break

            self._fire(steps)

            index += 1
            self.stats.repeats_done = index
            if self._on_progress:
                self._on_progress(self.stats)

            # Absolute re-anchor: the next deadline is computed from the start, never from "now",
            # so a slow click cannot push every later click back.
            interval = schedule.interval_ms(index)
            if interval is None:
                break
            deadline_ms = start_ms + index * interval
            if interval > 0 and self._time_fn() > deadline_ms + timing.LATE_TOLERANCE_MS:
                self.stats.missed_ticks += 1
                late = self._time_fn() - deadline_ms
                if late > self.stats.max_late_ms:
                    self.stats.max_late_ms = late

        self.stats.finished_at_ms = self._time_fn()

    def _schedule_for(self, profile: Profile) -> Schedule:
        return schedule_for(profile)

    def _sleep_until(self, deadline_ms: int, _start: int) -> bool:
        """
        Sleep until an absolute time. Returns True if the run should abort (stop was pressed).

        Sleeps in short slices so Stop is responsive even with a 30-minute wait. A single long sleep
        would make Stop appear broken, which is worse than a slightly busier loop.
        """
        while True:
            if self._stop.is_set():
                return True
            remaining = deadline_ms - self._time_fn()
            if remaining <= 0:
                return False
            self._sleep_fn(min(remaining, 25))

    def _fire(self, steps: list[Step]) -> None:
        for step in steps:
            if self._stop.is_set():
                return
            if isinstance(step, ClickStep):
                if step.position == "fixed":
                    self._backend.move(step.x, step.y)
                for _ in range(step.at_once):
                    self._backend.click(step.button, step.double)
                    self.stats.clicks_sent += 1
            elif isinstance(step, KeyStep):
                self._fire_chord(step)
            elif isinstance(step, WaitStep):
                self._sleep_fn(step.ms)

    def _fire_chord(self, step: KeyStep) -> None:
        """
        Press the keys with a gap, then release in reverse order with the same gap.

        Reverse release is what a real keyboard does for a chord: ctrl goes down first and comes up
        last. Releasing in the same order can drop the modifier on some applications.
        """
        for k in step.keys:
            if self._stop.is_set():
                return
            self._backend.key_down(k)
            self.stats.keys_sent += 1
            if step.gap_ms:
                self._sleep_fn(step.gap_ms)
        if step.hold_ms:
            self._sleep_fn(step.hold_ms)
        for k in reversed(step.keys):
            self._backend.key_up(k)
            if step.gap_ms:
                self._sleep_fn(step.gap_ms)


def _local_clock() -> tuple[int, int, int]:
    import time as _t

    lt = _t.localtime()
    return lt.tm_hour, lt.tm_min, lt.tm_sec


# Re-exported so callers do not need to know which module owns them.
__all__ = ["Engine", "InputBackend", "RunStats", "ParseError", "ProfileError",
           "parse_start_time", "parse_duration", "Schedule"]
