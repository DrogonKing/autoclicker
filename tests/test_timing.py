"""
Timing and scheduling tests.

These run on any platform because the core has no platform dependency. That is the point: the
arithmetic that decides when a click happens is the part that goes wrong, and it is tested here
rather than being assumed.
"""

from __future__ import annotations

import pytest

from autoclick.core import timing
from autoclick.core.errors import ParseError, ProfileError
from autoclick.core.model import Profile
from autoclick.core.schedule import (
    BackToBack,
    FixedInterval,
    parse_duration,
    parse_start_time,
    schedule_for,
)


class TestNoDrift:
    """
    The headline claim: deadlines are absolute, so a slow click cannot push later ones back.

    A sleepy implementation would fail every one of these, which is the reason they exist.
    """

    def test_deadlines_are_a_straight_line(self):
        start = 1_000_000
        # click 0 at t0, click 9999 exactly 9999 intervals later, regardless of anything between
        assert timing.deadline_for(0, 100, start) == start
        assert timing.deadline_for(1, 100, start) == start + 100
        assert timing.deadline_for(10_000, 100, start) == start + 1_000_000

    def test_no_sleep_when_the_deadline_has_arrived(self):
        d = timing.next_tick(5, 100, 0, now_ms=500)
        assert d.sleep_ms == 0
        assert not d.missed

    def test_sleeps_the_exact_remainder(self):
        # 30 ms late for the 500 ms deadline: sleep the other 70
        d = timing.next_tick(5, 100, 0, now_ms=470)
        assert d.sleep_ms == 30
        assert not d.missed

    def test_slightly_late_still_fires(self):
        d = timing.next_tick(5, 100, 0, now_ms=520)
        assert d.sleep_ms == 0
        assert not d.missed, "20 ms late is normal jitter, not a stall"

    def test_hopelessly_late_is_reported_not_crammed(self):
        """
        A machine that fell a whole second behind must not fire 10 clicks to catch up.

        This is the behaviour that matters: catching up would look like a burst of clicks the user
        never asked for, at the worst possible moment.
        """
        d = timing.next_tick(5, 100, 0, now_ms=1_500)
        assert d.missed
        assert d.late_by_ms == 1_000
        assert d.sleep_ms == 0, "fires immediately, but is flagged as missed"

    def test_late_tolerance_boundary(self):
        exactly = timing.LATE_TOLERANCE_MS
        assert not timing.next_tick(1, 0, 0, now_ms=exactly).missed
        assert timing.next_tick(1, 0, 0, now_ms=exactly + 1).missed

    def test_total_time_is_independent_of_per_click_cost(self):
        """
        Simulate a click that takes 7 ms, and confirm the 200th click is still at 200*interval.

        With `sleep(interval)` after each click, click 200 would be 1400 ms late. With absolute
        deadlines it is on time.
        """
        interval = 100
        start = 0
        click_cost = 7
        now = start
        fired_at = []
        for index in range(200):
            due = timing.deadline_for(index, interval, start)
            decision = timing.next_tick(index, interval, start, now)
            now = max(now, due) + click_cost   # the click itself costs time
            fired_at.append(max(due, now - click_cost))
            if decision.missed:  # pragma: no cover - must not happen at this cost
                pytest.fail(f"tick {index} was reported late though it cannot be")
        # the last click is at 199*interval, plus at most one click's cost of slack
        assert fired_at[-1] == 199 * interval, f"drifted to {fired_at[-1]}"


class TestHz:
    def test_ten_per_second_is_100ms(self):
        assert timing.interval_from_hz(10) == 100

    def test_one_thousand_per_second_is_1ms(self):
        assert timing.interval_from_hz(1000) == 1

    def test_beyond_timer_resolution_is_rejected(self):
        with pytest.raises(ValueError):
            timing.interval_from_hz(2000)

    def test_zero_is_rejected(self):
        with pytest.raises(ValueError):
            timing.interval_from_hz(0)


class TestClockTarget:
    def test_future_time_today(self):
        # now 11:50:00, target 11:50:20 -> 20 s
        assert timing.ms_until_clock("11:50:20", (11, 50, 0)) == 20_000

    def test_past_time_means_tomorrow(self):
        """
        A user typing 11:50 at 12:00 means the next 11:50, not a negative delay.

        Getting this wrong makes the app fire instantly, which is the opposite of what was asked.
        """
        got = timing.ms_until_clock("11:50:00", (12, 0, 0))
        assert got == 23 * 3600_000 + 50 * 60_000, f"got {got} ms"

    def test_exactly_now_is_zero(self):
        assert timing.ms_until_clock("11:50:20", (11, 50, 20)) == 0

    def test_seconds_and_minutes_are_respected(self):
        assert timing.ms_until_clock("00:00:01", (23, 59, 59)) == 2_000

    def test_round_trip_with_clock_from_ms(self):
        for now in ((0, 0, 0), (11, 50, 20), (23, 59, 59)):
            h, m, s = now
            ms_of_day = (h * 3600 + m * 60 + s) * 1000
            assert timing.clock_from_ms_of_day(ms_of_day) == f"{h:02d}:{m:02d}:{s:02d}"


class TestScheduleSelection:
    def test_positive_interval_is_fixed(self):
        s = schedule_for(Profile(interval_ms=250))
        assert isinstance(s, FixedInterval)
        assert s.interval == 250

    def test_zero_interval_is_back_to_back(self):
        """
        Zero is a different schedule, not a fast one.

        It skips deadline arithmetic entirely, which is what makes "as fast as possible" honest about
        reporting an achieved rate rather than an interval it never held to.
        """
        s = schedule_for(Profile(interval_ms=0))
        assert isinstance(s, BackToBack)
        assert s.interval_ms(0) == 0

    def test_wait_before_is_zero_for_the_first_tick(self):
        s = FixedInterval(interval=500)
        assert s.wait_before(0, 0) == 0

    def test_wait_before_catches_up_without_overshooting(self):
        s = FixedInterval(interval=500)
        # tick 3 is due at 1500; elapsed 1200 means wait 300
        assert s.wait_before(3, 1200) == 300
        # already past it: no negative sleep
        assert s.wait_before(3, 1600) == 0


class TestParseDuration:
    @pytest.mark.parametrize("text,expected", [
        ("500ms", 500),
        ("0", 0),
        ("90", 90),          # a bare number is milliseconds
        ("1s", 1000),
        ("1.5s", 1500),
        ("2m", 120_000),
        ("1h", 3_600_000),
        ("1h30m", 5_400_000),
        ("2m15s", 135_000),
        ("250 ms", 250),
    ])
    def test_accepted_forms(self, text, expected):
        assert parse_duration(text) == expected

    def test_bare_number_is_milliseconds_not_seconds(self):
        """
        The unit has to be decided somewhere, and milliseconds is the unit of the whole app.

        Guessing seconds for "500" would turn a half-second pause into eight minutes.
        """
        assert parse_duration("500") == 500

    @pytest.mark.parametrize("bad", ["", "   ", "abc", "1x", "-5"])
    def test_rejected(self, bad):
        with pytest.raises(ParseError):
            parse_duration(bad)


class TestParseStartTime:
    def test_clock_time(self):
        assert parse_start_time("11:50:20") == ("11:50:20", 0)

    def test_clock_time_without_seconds(self):
        assert parse_start_time("11:50") == ("11:50", 0)

    def test_relative_delay(self):
        assert parse_start_time("2.5s") == ("", 2500)

    def test_explicit_plus_delay(self):
        assert parse_start_time("+1500") == ("", 1500)

    def test_empty_means_immediate(self):
        assert parse_start_time("") == ("", 0)

    def test_exactly_one_of_the_two_is_returned(self):
        """
        Never both, so the caller cannot confuse "at 11:50" with "in 11:50".

        The empty input is the one case where neither is set, and that is meaningful: start now.
        """
        for text in ("11:50:20", "2.5s", "+900"):
            clock, delay = parse_start_time(text)
            assert bool(clock) != bool(delay), f"{text!r} returned both/neither: {clock!r}, {delay!r}"

        # "" means start immediately: no clock target and no delay, and the two are not ambiguous
        # because there is nothing to be ambiguous about
        assert parse_start_time("") == ("", 0)

    def test_pasted_iso_timestamp_takes_the_time(self):
        assert parse_start_time("2026-01-02T11:50:20") == ("11:50:20", 0)

    def test_malformed_clock_is_rejected_with_a_useful_message(self):
        with pytest.raises(ParseError) as e:
            parse_start_time("25:00")
        assert "hour" in str(e.value)

        with pytest.raises(ParseError) as e2:
            parse_start_time("11:70")
        assert "minute" in str(e2.value)
