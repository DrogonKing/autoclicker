"""
UI state tests.

These need a real Tk, so they run under Xvfb (or any display). They exist because the UI has its own
class of bug that the core tests cannot see: the interface can end up in a state the user cannot get
out of, even when every click was correct.

The specific suspicion here is the handoff between the engine thread and the widget state. The engine
reports progress from its own thread; the UI marshals that onto the Tk thread with `after`. If the
final state transition depends on a callback that arrives while the engine is still alive, the last
one may never come - leaving Start greyed out after a perfectly normal run.
"""
from __future__ import annotations

import time
import tkinter as tk

import pytest

from autoclick.core.engine import Engine
from autoclick.core.model import Profile
from autoclick.core.wininput import NullBackend


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as e:  # pragma: no cover - no display available
        pytest.skip(f"no display for Tk: {e}")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


def pump(root: tk.Tk, seconds: float = 2.0) -> None:
    """Run the Tk event loop for a while, so `after` callbacks are delivered."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(0.01)


class TestButtonStateAfterARun:
    def test_start_is_re_enabled_after_a_run_completes(self, root):
        """
        The user must be able to start again.

        Without this the app is usable exactly once per launch: the deferred `after` that would restore
        the buttons is scheduled while the engine is still alive, so `_refresh_status` sees
        is_running() True and declines to call `_after_run`, and then no further callback ever arrives.
        """
        from autoclick.ui.app import App

        app = App(root)
        app.v_button.set("left")
        app.v_interval.set("1")
        app.v_count.set("3")

        app._start(dry=True)
        pump(root, 3.0)

        assert str(app.start_btn["state"]) == "normal", (
            "Start stayed disabled after a completed run; the app would be usable only once"
        )
        assert str(app.stop_btn["state"]) == "disabled"
        assert app.engine is not None and not app.engine.is_running()

    def test_status_ends_in_the_ready_state(self, root):
        from autoclick.ui.app import App

        app = App(root)
        app.v_interval.set("1")
        app.v_count.set("3")
        app._start(dry=True)
        pump(root, 3.0)
        assert "ready" in app.status_box["text"].lower() or app.tr("s.ready") in app.status_box["text"]

    def test_stats_are_shown_not_just_claimed(self, root):
        from autoclick.ui.app import App

        app = App(root)
        app.v_interval.set("1")
        app.v_count.set("4")
        app._start(dry=True)
        pump(root, 3.0)
        assert app.stat_labels["s.clicks"]["text"] == "4"
        assert app.stat_labels["s.repeats"]["text"] == "4"

    def test_stop_from_the_button_restores_the_state(self, root):
        from autoclick.ui.app import App

        app = App(root)
        app.v_interval.set("50")
        app.v_count.set("0")  # unlimited, so it must be stopped
        app._start(dry=True)
        pump(root, 0.5)
        app._stop()
        pump(root, 1.0)
        assert str(app.start_btn["state"]) == "normal"
        assert str(app.stop_btn["state"]) == "disabled"


class TestInvalidInput:
    def test_a_bad_interval_is_reported_and_does_not_start(self, root, monkeypatch):
        """
        Nothing may start when the input is unreadable, and the user must be told why.

        An error dialog would block a headless test, so messagebox is captured instead.
        """
        from autoclick.ui import app as app_mod

        seen = []
        monkeypatch.setattr(app_mod.messagebox, "showerror", lambda *a, **k: seen.append(a))

        a = app_mod.App(root)
        a.v_interval.set("not a number")
        a.v_count.set("5")
        a._start(dry=True)

        assert seen, "no error was reported for an unreadable interval"
        assert a.engine is None or not a.engine.is_running()
        assert str(a.start_btn["state"]) == "normal", "the buttons were left in the running state"

    def test_a_bad_start_time_is_reported(self, root, monkeypatch):
        from autoclick.ui import app as app_mod

        seen = []
        monkeypatch.setattr(app_mod.messagebox, "showerror", lambda *a, **k: seen.append(a))

        a = app_mod.App(root)
        a.v_interval.set("10")
        a.v_start.set("99:99")
        a._start(dry=True)
        assert seen, "no error was reported for an unreadable start time"


class TestGather:
    def test_gather_produces_a_valid_profile(self, root):
        from autoclick.ui.app import App

        app = App(root)
        app.v_interval.set("250")
        app.v_count.set("100")
        app.v_start.set("11:50:20")
        app.v_at_once.set("3")
        p = app._gather()
        p.validate()  # must not raise
        assert p.interval_ms == 250
        assert p.repeat == 100
        assert p.start_at == "11:50:20"
        assert p.at_once == 3

    def test_gather_treats_a_delay_correctly(self, root):
        from autoclick.ui.app import App

        app = App(root)
        app.v_interval.set("10")
        app.v_start.set("2s")
        p = app._gather()
        # exactly one of the two must be set: "at 11:50" and "in 11:50" are different requests
        assert p.start_at == ""
        assert p.start_in_ms == 2000

    def test_advanced_mode_is_chosen_when_steps_exist(self, root):
        from autoclick.core.model import ClickStep
        from autoclick.ui.app import App

        app = App(root)
        app.steps = [ClickStep(), ClickStep()]
        p = app._gather()
        assert p.mode == "advanced"
        assert len(p.compile_steps()) == 2

    def test_simple_mode_is_chosen_with_no_steps(self, root):
        from autoclick.ui.app import App

        app = App(root)
        app.steps = []
        assert app._gather().mode == "simple"

    def test_a_negative_interval_is_not_silently_accepted(self, root, monkeypatch):
        """max(0, ...) clamps it, which is fine, but the profile must stay valid."""
        from autoclick.ui.app import App

        app = App(root)
        app.v_interval.set("-5")
        p = app._gather()
        p.validate()
        assert p.interval_ms == 0


class TestStepEditing:
    def test_add_and_remove_a_step(self, root):
        from autoclick.ui.app import App

        app = App(root)
        app.steps = []
        app._add_step("click")
        app._add_step("key")
        app._add_step("wait")
        assert len(app.steps) == 3
        app.steps_box.selection_set(1)
        app._remove_step()
        assert len(app.steps) == 2

    def test_move_a_step_up_and_down(self, root):
        from autoclick.ui.app import App

        app = App(root)
        app.steps = []
        app._add_step("click")
        app._add_step("wait")
        first = app.steps[0]
        app.steps_box.selection_set(1)
        app._move_step(-1)
        assert app.steps[0] is not first
        app.steps_box.selection_set(0)
        app._move_step(1)
        assert app.steps[1] is not first

    def test_moving_past_the_end_is_a_no_op(self, root):
        from autoclick.ui.app import App

        app = App(root)
        app.steps = []
        app._add_step("click")
        app.steps_box.selection_set(0)
        before = list(app.steps)
        app._move_step(-1)
        app._move_step(1)
        assert app.steps == before

    def test_an_added_key_step_parses_the_keys_field(self, root):
        from autoclick.core.model import KeyStep
        from autoclick.ui.app import App

        app = App(root)
        app.steps = []
        app.v_keys.set("ctrl shift t")
        app.v_gap.set("45")
        app._add_step("key")
        step = app.steps[0]
        assert isinstance(step, KeyStep)
        assert step.keys == ["ctrl", "shift", "t"]
        assert step.gap_ms == 45

    def test_an_empty_keys_field_falls_back_rather_than_creating_a_keyless_chord(self, root):
        """A chord with no keys would be a step that does nothing, silently."""
        from autoclick.core.model import KeyStep
        from autoclick.ui.app import App

        app = App(root)
        app.steps = []
        app.v_keys.set("   ")
        app._add_step("key")
        step = app.steps[0]
        assert isinstance(step, KeyStep)
        assert step.keys, "a key step was created with no keys"


class TestProfilePersistence:
    def test_save_and_reload_round_trips_through_the_ui(self, root, tmp_path, monkeypatch):
        from autoclick.ui import app as app_mod
        from autoclick.ui import store

        monkeypatch.setattr(store, "profiles_file", lambda: tmp_path / "profiles.json")
        a = app_mod.App(root)
        a.profiles = []
        a.v_name.set("my profile")
        a.v_interval.set("123")
        a.v_count.set("7")
        a.steps = []
        a._save_profile()

        reloaded = store.load_profiles(tmp_path / "profiles.json")
        assert len(reloaded) == 1
        assert reloaded[0].name == "my profile"
        assert reloaded[0].interval_ms == 123
        assert reloaded[0].repeat == 7

    def test_saving_twice_under_one_name_replaces_rather_than_duplicates(self, root, tmp_path, monkeypatch):
        from autoclick.ui import app as app_mod
        from autoclick.ui import store

        monkeypatch.setattr(store, "profiles_file", lambda: tmp_path / "profiles.json")
        a = app_mod.App(root)
        a.profiles = []
        a.v_name.set("same")
        a.steps = []
        a.v_interval.set("10")
        a._save_profile()
        a.v_interval.set("20")
        a._save_profile()
        assert len(a.profiles) == 1
        assert a.profiles[0].interval_ms == 20

    def test_an_invalid_profile_is_not_saved(self, root, tmp_path, monkeypatch):
        from autoclick.ui import app as app_mod
        from autoclick.ui import store

        monkeypatch.setattr(store, "profiles_file", lambda: tmp_path / "profiles.json")
        seen = []
        monkeypatch.setattr(app_mod.messagebox, "showerror", lambda *a, **k: seen.append(a))

        a = app_mod.App(root)
        a.profiles = []
        a.v_interval.set("rubbish")
        a.steps = []
        a._save_profile()

        assert seen, "no error was shown for an unreadable interval"
        assert not (tmp_path / "profiles.json").exists(), "an invalid profile was written to disk"

    def test_loading_a_profile_restores_every_field(self, root):
        from autoclick.core.model import Profile
        from autoclick.ui.app import App

        a = App(root)
        a.profiles = [Profile(
            name="loaded", interval_ms=333, repeat=9, start_at="07:30:00",
            position="fixed", x=111, y=222, at_once=4, double=True, max_duration_ms=5000,
        )]
        a.profile_box.delete(0, tk.END)
        for p in a.profiles:
            a.profile_box.insert(tk.END, p.name)
        a.profile_box.selection_set(0)
        a._load_selected()

        assert a.v_interval.get() == "333"
        assert a.v_count.get() == "9"
        assert a.v_start.get() == "07:30:00"
        assert a.v_x.get() == "111"
        assert a.v_y.get() == "222"
        assert a.v_at_once.get() == "4"
        assert a.v_double.get() is True
        assert a.v_maxdur.get() == "5000"
