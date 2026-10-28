"""
Engine tests.

The engine takes an injected clock and sleep, so a run of 10,000 clicks completes in milliseconds and
every click's position in time can be asserted exactly. Without that injection these tests could only
be written as "wait 4 seconds and hope", which is how flaky suites are born.
"""

from __future__ import annotations

import pytest

from autoclick.core.engine import Engine, RunStats
from autoclick.core.errors import ProfileError
from autoclick.core.model import ClickStep, KeyStep, Profile, WaitStep
from autoclick.core.wininput import NullBackend


class FakeClock:
    """
    A clock that only moves when something sleeps.

    Sleeps are recorded rather than performed, so the test asserts on the exact sleep pattern the
    engine chose - which is where drift bugs live - instead of on wall-clock timing.
    """

    def __init__(self, start_ms: int = 0, clock: tuple[int, int, int] = (0, 0, 0)) -> None:
        self.now = start_ms
        self.slept: list[float] = []
        self._clock = clock
        self.per_sleep_cost = 0  # ms of work simulated for each sleep call

    def time(self) -> int:
        return self.now

    def sleep(self, ms: float) -> None:
        self.slept.append(ms)
        self.now += int(ms) + self.per_sleep_cost

    def advance(self, ms: int) -> None:
        self.now += ms

    def wall_clock(self) -> tuple[int, int, int]:
        return self._clock


def make_engine(clock: FakeClock, backend=None) -> Engine:
    return Engine(
        backend or NullBackend(clock.time),
        time_fn=clock.time,
        sleep_fn=clock.sleep,
        now_clock=clock.wall_clock,
    )


class TestRepeatCount:
    def test_exactly_n_clicks(self):
        """
        "100 clicks" must mean exactly 100.

        A loop that checks elapsed time instead of a counter overshoots or undershoots depending on
        how fast the machine is.
        """
        clock = FakeClock()
        backend = NullBackend(clock.time)
        engine = make_engine(clock, backend)
        stats = engine.run_blocking(Profile(interval_ms=10, repeat=100))
        assert stats.clicks_sent == 100
        assert len(backend.click_times()) == 100

    def test_repeat_one(self):
        clock = FakeClock()
        backend = NullBackend(clock.time)
        stats = make_engine(clock, backend).run_blocking(Profile(interval_ms=10, repeat=1))
        assert stats.clicks_sent == 1

    def test_unlimited_stops_on_request(self):
        """repeat=0 means unlimited, and stop() must end it."""
        clock = FakeClock()
        backend = NullBackend(clock.time)
        engine = make_engine(clock, backend)

        def stop_after_50(_stats: RunStats) -> None:
            if _stats.clicks_sent >= 50:
                engine.stop("test stop")

        engine.on_progress(stop_after_50)
        engine.run_blocking(Profile(interval_ms=1, repeat=0))
        assert backend.click_times().__len__() == 50
        assert engine.stats.stopped_by == "test stop"


class TestSimultaneousClicks:
    def test_at_once_fires_the_same_instant(self):
        """
        "چندتا کلیک همزمان": several clicks with no gap.

        Asserted on the timestamps, not the count: the count would pass even if the engine slept
        between them, which is the bug this guards.
        """
        clock = FakeClock()
        backend = NullBackend(clock.time)
        stats = make_engine(clock, backend).run_blocking(
            Profile(interval_ms=0, repeat=1, at_once=3)
        )
        times = backend.click_times()
        assert len(times) == 3
        assert len(set(times)) == 1, f"simultaneous clicks were spread over {set(times)}"
        assert stats.clicks_sent == 3

    def test_at_once_applies_every_repetition(self):
        clock = FakeClock()
        backend = NullBackend(clock.time)
        stats = make_engine(clock, backend).run_blocking(
            Profile(interval_ms=50, repeat=4, at_once=3)
        )
        assert stats.clicks_sent == 12
        # four instants, each with three clicks
        assert len(set(backend.click_times())) == 4

    def test_at_once_is_not_limited_to_the_repeat_count(self):
        """The count is repetitions, not clicks. Three at once, twice, is six clicks."""
        clock = FakeClock()
        backend = NullBackend(clock.time)
        stats = make_engine(clock, backend).run_blocking(
            Profile(interval_ms=5, repeat=2, at_once=3)
        )
        assert stats.repeats_done == 2
        assert stats.clicks_sent == 6


class TestKeyChords:
    def test_chord_uses_the_configured_gap(self):
        """
        "چندتا کلید با فاصله زمانی چند میلی ثانیه": the gap must be what the user set.

        A chord with no gap is delivered as one instantaneous event and many applications ignore the
        modifiers, so the gap is the feature, not a detail.
        """
        clock = FakeClock()
        backend = NullBackend(clock.time)
        profile = Profile(
            mode="advanced", interval_ms=100, repeat=1,
            steps=[KeyStep(keys=["ctrl", "shift", "t"], gap_ms=25)],
        )
        make_engine(clock, backend).run_blocking(profile)

        downs = [int(p[1]) for k, p in backend.events if k == "key_down"]  # type: ignore[index]
        assert len(downs) == 3
        assert downs[1] - downs[0] == 25, f"gap was {downs[1] - downs[0]} ms, expected 25"
        assert downs[2] - downs[1] == 25

    def test_keys_release_in_reverse_order(self):
        """
        A real keyboard releases the modifier last.

        Releasing in the same order can drop the modifier in some applications, producing a plain 't'
        instead of ctrl+shift+t.
        """
        clock = FakeClock()
        backend = NullBackend(clock.time)
        profile = Profile(
            mode="advanced", interval_ms=100, repeat=1,
            steps=[KeyStep(keys=["ctrl", "shift", "t"], gap_ms=5)],
        )
        make_engine(clock, backend).run_blocking(profile)

        order = [(k, p[0]) for k, p in backend.events if k in ("key_down", "key_up")]  # type: ignore[index]
        downs = [x[1] for x in order if x[0] == "key_down"]
        ups = [x[1] for x in order if x[0] == "key_up"]
        assert downs == ["ctrl", "shift", "t"]
        assert ups == ["t", "shift", "ctrl"], f"released as {ups}"

    def test_hold_time_between_down_and_up(self):
        clock = FakeClock()
        backend = NullBackend(clock.time)
        profile = Profile(
            mode="advanced", interval_ms=500, repeat=1,
            steps=[KeyStep(keys=["a"], gap_ms=0, hold_ms=120)],
        )
        make_engine(clock, backend).run_blocking(profile)

        down = next(int(p[1]) for k, p in backend.events if k == "key_down")  # type: ignore[index]
        up = next(int(p[1]) for k, p in backend.events if k == "key_up")      # type: ignore[index]
        assert up - down == 120

    def test_every_key_counts_in_the_stats(self):
        clock = FakeClock()
        backend = NullBackend(clock.time)
        profile = Profile(
            mode="advanced", interval_ms=500, repeat=2,
            steps=[KeyStep(keys=["ctrl", "a"], gap_ms=1)],
        )
        stats = make_engine(clock, backend).run_blocking(profile)
        assert stats.keys_sent == 4  # two keys, two repetitions


class TestAdvancedSequence:
    def test_steps_run_in_order(self):
        clock = FakeClock()
        backend = NullBackend(clock.time)
        profile = Profile(
            mode="advanced", interval_ms=100, repeat=1,
            steps=[
                WaitStep(ms=10),
                ClickStep(button="left"),
                KeyStep(keys=["enter"], gap_ms=0),
                ClickStep(button="right", position="fixed", x=500, y=400),
            ],
        )
        make_engine(clock, backend).run_blocking(profile)

        kinds = [k for k, _ in backend.events]
        assert kinds == ["click", "key_down", "key_up", "move", "click"]

    def test_fixed_position_moves_before_clicking(self):
        """
        The move must precede the click in the event stream.

        Sending them the other way round clicks wherever the pointer happened to be, which is a bug a
        count-based test would never catch.
        """
        clock = FakeClock()
        backend = NullBackend(clock.time)
        profile = Profile(
            mode="advanced", interval_ms=100, repeat=1,
            steps=[ClickStep(position="fixed", x=123, y=456)],
        )
        make_engine(clock, backend).run_blocking(profile)

        assert backend.events[0][0] == "move"
        assert backend.events[0][1][:2] == (123, 456)  # type: ignore[index]
        assert backend.events[1][0] == "click"

    def test_cursor_mode_does_not_move(self):
        clock = FakeClock()
        backend = NullBackend(clock.time)
        profile = Profile(
            mode="advanced", interval_ms=100, repeat=1,
            steps=[ClickStep(position="cursor")],
        )
        make_engine(clock, backend).run_blocking(profile)
        assert not [k for k, _ in backend.events if k == "move"]

    def test_double_click_sends_two_presses(self):
        clock = FakeClock()
        backend = NullBackend(clock.time)
        profile = Profile(interval_ms=100, repeat=1, double=True)
        make_engine(clock, backend).run_blocking(profile)
        assert len([k for k, _ in backend.events if k == "click"]) == 1
        assert backend.events[0][1][1] is True  # type: ignore[index]


class TestStartTime:
    def test_relative_delay_is_honoured(self):
        clock = FakeClock(start_ms=0)
        backend = NullBackend(clock.time)
        stats = make_engine(clock, backend).run_blocking(
            Profile(interval_ms=10, repeat=1, start_in_ms=2000)
        )
        first = backend.click_times()[0]
        assert first >= 2000, f"clicked at {first} ms, before the 2000 ms start delay"
        assert stats.clicks_sent == 1

    def test_clock_time_waits_until_that_time(self):
        # now 11:50:00, start at 11:50:20 -> the first click is 20 s away
        clock = FakeClock(start_ms=0, clock=(11, 50, 0))
        backend = NullBackend(clock.time)
        make_engine(clock, backend).run_blocking(
            Profile(interval_ms=10, repeat=1, start_at="11:50:20")
        )
        first = backend.click_times()[0]
        assert first >= 20_000, f"clicked at {first} ms, before the 20 s target"
        assert first < 21_000, "should not wait far past the target"

    def test_immediate_start_has_no_wait(self):
        clock = FakeClock(start_ms=0)
        backend = NullBackend(clock.time)
        make_engine(clock, backend).run_blocking(Profile(interval_ms=10, repeat=1))
        assert backend.click_times()[0] == 0


class TestSafetyGuards:
    def test_max_duration_stops_a_runaway(self):
        """
        An unlimited profile must still be able to stop itself.

        This is the guard for "I started it and walked away".
        """
        clock = FakeClock(start_ms=0)
        backend = NullBackend(clock.time)
        engine = make_engine(clock, backend)
        engine.run_blocking(Profile(interval_ms=10, repeat=0, max_duration_ms=500))
        assert engine.stats.stopped_by == "max duration reached"
        # with a 10 ms interval and a 500 ms cap: roughly 50 clicks, never thousands
        assert 40 <= engine.stats.clicks_sent <= 60, f"sent {engine.stats.clicks_sent}"

    def test_stop_is_honoured_during_a_long_wait(self):
        """
        Stop must work while waiting for a clock target, not only between clicks.

        A single long sleep would make Stop look broken for up to 24 hours.
        """
        clock = FakeClock(start_ms=0, clock=(0, 0, 0))
        backend = NullBackend(clock.time)
        engine = make_engine(clock, backend)

        # a target far in the future: 23:59:59 from midnight
        calls = {"n": 0}

        def original_sleep(ms: float) -> None:
            clock.slept.append(ms)
            clock.now += int(ms)
            calls["n"] += 1
            if calls["n"] >= 5:
                engine.stop("user pressed stop")

        engine._sleep_fn = original_sleep  # type: ignore[attr-defined]
        engine.run_blocking(Profile(interval_ms=10, repeat=1, start_at="23:59:59"))

        assert engine.stats.stopped_by == "user pressed stop"
        assert engine.stats.clicks_sent == 0, "clicked despite being stopped during the wait"

    def test_invalid_profile_does_not_run(self):
        clock = FakeClock()
        backend = NullBackend(clock.time)
        engine = make_engine(clock, backend)
        engine.run_blocking(Profile(interval_ms=10, repeat=1, button="banana"))  # type: ignore[arg-type]
        assert engine.stats.stopped_by == "invalid"
        assert "banana" in engine.stats.error
        assert engine.stats.clicks_sent == 0

    def test_empty_advanced_profile_is_refused(self):
        clock = FakeClock()
        engine = make_engine(clock, NullBackend(clock.time))
        engine.run_blocking(Profile(mode="advanced", steps=[]))
        assert engine.stats.stopped_by == "invalid"
        assert "at least one step" in engine.stats.error


class TestStats:
    def test_stats_are_truthful(self):
        clock = FakeClock()
        backend = NullBackend(clock.time)
        stats = make_engine(clock, backend).run_blocking(
            Profile(interval_ms=25, repeat=7, at_once=2)
        )
        assert stats.repeats_done == 7
        assert stats.clicks_sent == 14
        d = stats.as_dict()
        assert d["clicks_sent"] == 14
        assert d["repeats_done"] == 7
        assert "elapsed_ms" in d
