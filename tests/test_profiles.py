"""
Profile serialisation tests.

A saved profile is the only artefact that outlives a session, so it has to survive a round trip
exactly - including the parts a user would not notice going missing.
"""

from __future__ import annotations

import json

import pytest

from autoclick.core.errors import ProfileError
from autoclick.core.model import (
    ClickStep,
    KeyStep,
    Profile,
    WaitStep,
    from_dict,
    to_dict,
)


class TestRoundTrip:
    def test_simple_profile_survives(self):
        original = Profile(
            name="farm", interval_ms=250, repeat=1000, button="right",
            position="fixed", x=960, y=540, at_once=2, double=True,
            start_at="11:50:20", max_duration_ms=60_000, hotkey="f7",
        )
        restored = from_dict(to_dict(original))
        assert to_dict(restored) == to_dict(original)

    def test_advanced_profile_survives_with_step_types_intact(self):
        """A step silently becoming a different kind is how a profile turns into a no-op."""
        original = Profile(
            name="combo", mode="advanced", interval_ms=500, repeat=3,
            steps=[
                WaitStep(ms=250),
                ClickStep(button="left", at_once=3),
                KeyStep(keys=["ctrl", "shift", "t"], gap_ms=40, hold_ms=15),
                ClickStep(position="fixed", x=-100, y=50),
            ],
        )
        restored = from_dict(to_dict(original))
        kinds = [s.kind for s in restored.steps]
        assert kinds == ["wait", "click", "key", "click"]

        key_step = next(s for s in restored.steps if isinstance(s, KeyStep))
        assert key_step.keys == ["ctrl", "shift", "t"]
        assert key_step.gap_ms == 40
        assert key_step.hold_ms == 15

        fixed = [s for s in restored.steps if isinstance(s, ClickStep) and s.position == "fixed"]
        # negative coordinates are valid on a multi-monitor setup with a left-hand screen
        assert fixed[0].x == -100

    def test_serialised_form_is_plain_json(self):
        """It has to survive json.dumps, so nothing exotic may leak into the dict."""
        p = Profile(mode="advanced", steps=[KeyStep(keys=["a"]), WaitStep(ms=5)])
        text = json.dumps(to_dict(p))
        assert json.loads(text) == to_dict(p)

    def test_unicode_profile_name(self):
        p = Profile(name="کلیک سریع", interval_ms=10)
        assert from_dict(to_dict(p)).name == "کلیک سریع"


class TestRejection:
    def test_unknown_step_kind_is_an_error_not_a_default(self):
        """
        A silently-defaulted unknown step is a profile that does nothing, invisibly.

        Erroring means the user is told their file has a step the app does not understand.
        """
        with pytest.raises(ProfileError) as e:
            from_dict({"mode": "advanced", "steps": [{"kind": "teleport"}]})
        assert "teleport" in str(e.value)

    def test_missing_kind_is_an_error(self):
        with pytest.raises(ProfileError):
            from_dict({"mode": "advanced", "steps": [{}]})

    def test_steps_must_be_a_list(self):
        with pytest.raises(ProfileError) as e:
            from_dict({"mode": "advanced", "steps": {"kind": "click"}})
        assert "list" in str(e.value)

    def test_profile_must_be_an_object(self):
        with pytest.raises(ProfileError):
            from_dict(["not", "a", "profile"])
        with pytest.raises(ProfileError):
            from_dict("nope")

    def test_out_of_range_values_are_refused_on_load(self):
        """A hand-edited file must not be able to ask for a negative interval."""
        with pytest.raises(ProfileError):
            from_dict({"interval_ms": -5})
        with pytest.raises(ProfileError):
            from_dict({"repeat": -1})
        with pytest.raises(ProfileError):
            from_dict({"at_once": 0})
        with pytest.raises(ProfileError):
            from_dict({"at_once": 500})

    def test_bad_button_is_refused(self):
        with pytest.raises(ProfileError) as e:
            from_dict({"button": "banana"})
        assert "banana" in str(e.value)

    def test_bad_clock_is_refused_with_context(self):
        with pytest.raises(ProfileError) as e:
            from_dict({"start_at": "99:99"})
        assert "start time" in str(e.value)

    def test_unknown_extra_keys_are_ignored(self):
        """
        Forward compatibility: a file written by a newer build must still load.

        The alternative is a user losing their profiles after a downgrade.
        """
        p = from_dict({"interval_ms": 50, "something_from_the_future": {"a": 1}})
        assert p.interval_ms == 50

    def test_unknown_keys_inside_a_step_are_ignored(self):
        p = from_dict({
            "mode": "advanced",
            "steps": [{"kind": "click", "button": "middle", "future_field": True}],
        })
        step = p.steps[0]
        assert isinstance(step, ClickStep)
        assert step.button == "middle"


class TestCompile:
    def test_simple_mode_compiles_to_one_click_step(self):
        p = Profile(interval_ms=100, at_once=4, button="middle")
        steps = p.compile_steps()
        assert len(steps) == 1
        assert isinstance(steps[0], ClickStep)
        assert steps[0].at_once == 4
        assert steps[0].button == "middle"

    def test_advanced_mode_compiles_to_its_own_steps(self):
        p = Profile(mode="advanced", steps=[WaitStep(ms=1), ClickStep()])
        assert len(p.compile_steps()) == 2

    def test_compile_validates_first(self):
        """An invalid profile must not produce a step list that looks runnable."""
        with pytest.raises(ProfileError):
            Profile(interval_ms=-1).compile_steps()

    def test_total_keys_counts_every_key(self):
        p = Profile(
            mode="advanced", repeat=1,
            steps=[KeyStep(keys=["ctrl", "a"]), ClickStep(), KeyStep(keys=["enter"])],
        )
        assert p.total_keys() == 3

    def test_describe_is_readable(self):
        p = Profile(interval_ms=250, repeat=100, at_once=2, start_at="11:50:20")
        text = p.describe()
        assert "250 ms" in text
        assert "100" in text
        assert "11:50:20" in text

    def test_describe_says_unlimited_not_zero(self):
        """"count 0" reads as "no clicks"; the word matters."""
        assert "unlimited" in Profile(repeat=0).describe()
