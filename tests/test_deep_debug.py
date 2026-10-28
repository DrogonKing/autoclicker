"""
Deep-debug candidates.

Each test here targets a specific suspicion from reading the engine, and each one FAILS if the
suspicion is correct. A test that passes means the code is fine and I was wrong - both outcomes are
worth knowing.
"""
from __future__ import annotations

import pytest

from autoclick.core.engine import Engine, RunStats
from autoclick.core.model import ClickStep, KeyStep, Profile, WaitStep
from autoclick.core.wininput import NullBackend


class Clock:
    def __init__(self, start=0, clock=(0, 0, 0)):
        self.now = start
        self.slept = []
        self._clock = clock
        self.cost = 0  # simulated work cost per sleep call

    def time(self):
        return self.now

    def sleep(self, ms):
        self.slept.append(ms)
        self.now += int(ms) + self.cost

    def wall(self):
        return self._clock


def eng(c, back=None):
    return Engine(back or NullBackend(c.time), time_fn=c.time, sleep_fn=c.sleep, now_clock=c.wall)


# ==================================================================================================
# SUSPICION 1
# The loop only checks `max_duration_ms` BEFORE firing a tick. So one repetition that itself takes
# longer than the limit - a long WaitStep, or many key chords with gaps - runs to completion, and the
# run ends at with_duration + that repetition, not at with_duration.
# ==================================================================================================
class TestMaxDurationIsAHardCeiling:
    def test_a_long_wait_step_must_not_overrun_the_limit(self):
        """
        'Stop after 1 second' must stop after about one second.

        A 5-second WaitStep inside the repetition should be interrupted by the 1-second limit, not
        allowed to run to five seconds and then notice.
        """
        c = Clock()
        profile = Profile(
            mode="advanced", interval_ms=10, repeat=0, max_duration_ms=1000,
            steps=[WaitStep(ms=5000)],
        )
        engine = eng(c, NullBackend(c.time))
        engine.run_blocking(profile)
        ran = c.now
        assert ran <= 1100, (
            f"a 1s limit ran for {ran} ms because a 5000 ms wait inside the repetition was not "
            f"interrupted"
        )

    def test_many_key_gaps_must_not_overrun_the_limit(self):
        c = Clock()
        profile = Profile(
            mode="advanced", interval_ms=10, repeat=0, max_duration_ms=500,
            steps=[KeyStep(keys=["a", "b", "c", "d", "e", "f"], gap_ms=200)],
        )
        engine = eng(c, NullBackend(c.time))
        engine.run_blocking(profile)
        assert c.now <= 700, f"a 500 ms limit ran for {c.now} ms"


# ==================================================================================================
# SUSPICION 2
# 'Stop is honoured during a long wait' was only ever tested for the start-up delay. But a LONG
# INTERVAL between repetitions goes through `_sleep_until` too, and that path slices at 25 ms so it
# should be responsive. What about the interval sleep after a tick when interval is large? Same
# function, so this should pass - included to prove it, not assumed.
# ==================================================================================================
class TestStopResponsiveness:
    def test_stop_during_the_interval_gap(self):
        c = Clock()
        engine = eng(c, NullBackend(c.time))
        calls = {"n": 0}
        real = c.sleep

        def counting(ms):
            real(ms)
            calls["n"] += 1
            if calls["n"] > 3:
                engine.stop("user pressed stop")

        engine._sleep_fn = counting
        engine.run_blocking(Profile(interval_ms=60_000, repeat=5))
        assert engine.stats.stopped_by == "user pressed stop"
        assert engine.stats.clicks_sent <= 2, f"sent {engine.stats.clicks_sent} clicks"

    def test_stop_during_a_wait_step(self):
        """
        A WaitStep calls `_sleep_fn` directly in one lump. That means Stop cannot interrupt a long
        wait inside a sequence - the UI would freeze its Stop for the whole duration.
        """
        c = Clock()
        engine = eng(c, NullBackend(c.time))
        profile = Profile(
            mode="advanced", interval_ms=10, repeat=1,
            steps=[WaitStep(ms=30_000), ClickStep()],
        )
        real = c.sleep
        calls = {"n": 0}

        def counting(ms):
            real(ms)
            calls["n"] += 1
            if calls["n"] >= 2:
                engine.stop("user pressed stop")

        engine._sleep_fn = counting
        engine.run_blocking(profile)
        assert engine.stats.stopped_by == "user pressed stop"


# ==================================================================================================
# SUSPICION 3
# A key that goes down but never comes up is the worst failure this program can have: the user's
# keyboard stays stuck until they press it physically. Stop mid-chord must release what it pressed.
# ==================================================================================================
class TestNoStuckKeys:
    def test_stop_mid_chord_still_releases_every_key(self):
        c = Clock()
        backend = NullBackend(c.time)
        engine = eng(c, backend)

        # stop arrives while the chord is still pressing keys down
        real_sleep = c.sleep
        calls = {"n": 0}

        def sleep_and_stop(ms):
            real_sleep(ms)
            calls["n"] += 1
            if calls["n"] >= 1:
                engine.stop("user pressed stop")

        engine._sleep_fn = sleep_and_stop
        profile = Profile(
            mode="advanced", interval_ms=10, repeat=1,
            steps=[KeyStep(keys=["ctrl", "shift", "t"], gap_ms=50)],
        )
        engine.run_blocking(profile)

        downs = [p[0] for k, p in backend.events if k == "key_down"]
        ups = [p[0] for k, p in backend.events if k == "key_up"]
        missing = [k for k in downs if k not in ups]
        assert missing == [], f"these keys were pressed and never released: {missing}"

    def test_stop_immediately_after_key_down_releases_it(self):
        c = Clock()
        backend = NullBackend(c.time)
        engine = eng(c, backend)

        # a backend that stops the run the moment a key goes down
        class StoppingBackend(NullBackend):
            def key_down(self, key):
                super().key_down(key)
                engine.stop("stopped during key_down")

        stopping = StoppingBackend(c.time)
        engine._backend = stopping
        profile = Profile(
            mode="advanced", interval_ms=10, repeat=1,
            steps=[KeyStep(keys=["a", "b"], gap_ms=10)],
        )
        engine.run_blocking(profile)

        # both lists must come from the same recorder: comparing one backend's presses against
        # another's releases is what made the earlier version of this test lie
        downs = [p[0] for k, p in stopping.events if k == "key_down"]
        ups = [p[0] for k, p in stopping.events if k == "key_up"]
        assert downs, "the test is meaningless if no key was pressed"
        assert downs == ups, f"pressed {downs} but released {ups}"


# ==================================================================================================
# SUSPICION 4
# The missed-tick accounting compares against `start_ms + index*interval`, which is the deadline for
# the tick JUST FIRED, not the one about to fire. So a run that is chronically late may report zero
# missed ticks. Check the numbers, not just the absence of an exception.
# ==================================================================================================
class TestMissedTickAccounting:
    @staticmethod
    def _slow_click(c: "Clock", cost_ms: int):
        """A backend whose click itself costs time - the real case, a slow SendInput."""

        class SlowClick(NullBackend):
            def click(self, button, double=False):
                super().click(button, double)
                c.now += cost_ms

        return SlowClick(c.time)

    def test_a_click_that_fits_inside_its_slot_stays_on_time(self):
        """
        A 400 ms click in a 500 ms slot is ON TIME, and reporting it as late would be wrong.

        This is worth asserting because it is the behaviour that makes the absolute-deadline design
        worth having: the wait after each click is recomputed from elapsed time, so it waits 100 ms
        instead of 500 and the next click lands exactly on its deadline. I initially wrote this test the
        other way round, expecting lateness - the engine was right and I was wrong.
        """
        c = Clock()
        engine = eng(c, self._slow_click(c, 400))
        engine.run_blocking(Profile(interval_ms=500, repeat=5))
        assert engine.stats.max_late_ms == 0, (
            f"a click that fits its slot was reported {engine.stats.max_late_ms} ms late"
        )
        assert engine.stats.missed_ticks == 0
        # 5 clicks x 400 ms + 4 gaps x 100 ms, so the whole run is a little over 2 seconds
        assert 2000 <= c.now <= 2600, f"the run took {c.now} ms"

    def test_missed_ticks_counted_when_a_click_overruns_its_slot(self):
        """
        A 400 ms click in a 100 ms slot cannot be on time: it overruns by three whole slots.

        The counter must say so, because that is the number the user reads to decide whether the rate
        they asked for is achievable on their machine.
        """
        c = Clock()
        engine = eng(c, self._slow_click(c, 400))
        engine.run_blocking(Profile(interval_ms=100, repeat=5))
        assert engine.stats.missed_ticks > 0, (
            f"a 100 ms interval with a 400 ms click reported {engine.stats.missed_ticks} missed ticks"
        )
        assert engine.stats.max_late_ms > 0, "overrunning the slot is lateness by definition"

    def test_an_on_time_run_reports_no_lateness(self):
        c = Clock()
        engine = eng(c, NullBackend(c.time))
        engine.run_blocking(Profile(interval_ms=500, repeat=5))
        assert engine.stats.max_late_ms == 0
        assert engine.stats.missed_ticks == 0


# ==================================================================================================
# SUSPICION 5
# Once a tick is missed, the next deadline is index*interval, which may already be in the past - so
# the engine bursts to catch up, which is precisely what the design says it will not do.
# ==================================================================================================
class TestNoCatchUpBurst:
    def test_no_run_of_zero_sleep_ticks(self):
        c = Clock()
        c.cost = 950  # nearly a whole second of work per repetition
        engine = eng(c, NullBackend(c.time))
        engine.run_blocking(Profile(interval_ms=1000, repeat=4))
        # every repetition costs 950 ms with a 1000 ms interval, so no catch-up should be needed
        zero_sleeps = sum(1 for s in c.slept if s == 0)
        assert zero_sleeps <= 8, f"{zero_sleeps} zero-length sleeps suggests a catch-up burst"


# ==================================================================================================
# SUSPICION 6
# `start_in_ms` is validated against MAX_INTERVAL_MS, which happens to be 24h. So "+25h" is silently
# rejected or clamped - check which, because a silent clamp is a lie about what will happen.
# ==================================================================================================
class TestDelayBounds:
    def test_a_delay_longer_than_a_day_is_rejected_rather_than_clamped(self):
        from autoclick.core.errors import ProfileError

        with pytest.raises(ProfileError):
            Profile(start_in_ms=25 * 3600 * 1000).validate()

    def test_a_delay_just_under_a_day_is_allowed(self):
        Profile(start_in_ms=24 * 3600 * 1000 - 1).validate()


# ==================================================================================================
# SUSPICION 7
# BackToBack reports `interval_ms() == floor_ms` == 0, and the loop computes
# `deadline_ms = start + index*0` == start, then compares now > start + tolerance. After one second
# of spamming, that is true every iteration, so missed_ticks and max_late_ms both grow without bound
# even though nothing is wrong.
# ==================================================================================================
class TestBackToBackStatsAreNotNonsense:
    def test_zero_interval_does_not_report_absurd_lateness(self):
        c = Clock()
        engine = eng(c, NullBackend(c.time))
        engine.run_blocking(Profile(interval_ms=0, repeat=50))
        assert engine.stats.max_late_ms < 1000, (
            f"a 0 ms interval reported max_late_ms={engine.stats.max_late_ms}; there is no deadline "
            f"to be late for"
        )

    def test_zero_interval_does_not_report_missed_ticks(self):
        c = Clock()
        engine = eng(c, NullBackend(c.time))
        engine.run_blocking(Profile(interval_ms=0, repeat=50))
        assert engine.stats.missed_ticks == 0, (
            f"'as fast as possible' reported {engine.stats.missed_ticks} missed ticks over 50 clicks"
        )