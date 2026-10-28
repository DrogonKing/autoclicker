"""
Storage and hotkey-parsing tests.

Storage is what survives between sessions, so its failure modes matter more than most: a profile the
user spent time composing must not vanish because one field was unreadable. Hotkey parsing is pure
string work and testable anywhere; only registration needs Windows.
"""
from __future__ import annotations

import json
import sys

import pytest

from autoclick.core.errors import ProfileError
from autoclick.core.model import ClickStep, KeyStep, Profile, WaitStep
from autoclick.ui import store


class TestAtomicSave:
    def test_save_then_load_round_trips(self, tmp_path):
        p = tmp_path / "profiles.json"
        profiles = [
            Profile(name="a", interval_ms=10, repeat=5),
            Profile(name="b", mode="advanced", steps=[KeyStep(keys=["ctrl", "c"]), WaitStep(ms=7)]),
        ]
        store.save_profiles(profiles, p)
        back = store.load_profiles(p)
        assert [x.name for x in back] == ["a", "b"]
        assert back[1].mode == "advanced"

    def test_save_leaves_no_temporary_files_behind(self, tmp_path):
        """
        The write goes through a temp file and a replace, so an interrupted save cannot destroy the
        previous contents. The cost of that trick is leftovers if the cleanup is wrong.
        """
        p = tmp_path / "profiles.json"
        store.save_profiles([Profile(name="x")], p)
        store.save_profiles([Profile(name="y")], p)
        names = sorted(f.name for f in tmp_path.iterdir())
        assert names == ["profiles.json"], f"leftover files: {names}"

    def test_a_failed_write_does_not_destroy_the_previous_file(self, tmp_path, monkeypatch):
        p = tmp_path / "profiles.json"
        store.save_profiles([Profile(name="keep me")], p)
        before = p.read_text()

        # make the replace fail, as a full disk or a locked file would
        import os

        def boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            store.save_profiles([Profile(name="gone")], p)

        assert p.read_text() == before, "the previous profiles were lost by a failed save"
        # and the temp file must not be left behind either
        assert [f.name for f in tmp_path.iterdir()] == ["profiles.json"]


class TestCorruptionTolerance:
    def test_a_corrupt_file_loads_as_empty_rather_than_crashing(self, tmp_path):
        p = tmp_path / "profiles.json"
        p.write_text("{ this is not json")
        assert store.load_profiles(p) == []

    def test_one_bad_entry_does_not_discard_the_good_ones(self, tmp_path):
        """
        Losing nine good profiles because the tenth was hand-edited is not an acceptable failure.
        """
        p = tmp_path / "profiles.json"
        p.write_text(json.dumps({"version": 1, "profiles": [
            {"name": "good one", "interval_ms": 5},
            {"name": "bad", "interval_ms": -999},          # invalid
            {"name": "also bad", "button": "banana"},      # invalid
            {"name": "good two", "interval_ms": 6},
        ]}))
        got = store.load_profiles(p)
        assert [x.name for x in got] == ["good one", "good two"]

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        assert store.load_profiles(tmp_path / "nope.json") == []

    def test_a_json_list_without_the_wrapper_still_loads(self, tmp_path):
        """An older or hand-written file may be a bare list. Accept it rather than ignoring it."""
        p = tmp_path / "profiles.json"
        p.write_text(json.dumps([{"name": "bare", "interval_ms": 3}]))
        assert [x.name for x in store.load_profiles(p)] == ["bare"]

    def test_settings_corruption_is_tolerated(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text("not json at all")
        assert store.load_settings(p) == {}

    def test_settings_round_trip(self, tmp_path):
        p = tmp_path / "settings.json"
        store.save_settings({"language": "fa", "always_on_top": True}, p)
        assert store.load_settings(p) == {"language": "fa", "always_on_top": True}

    def test_unicode_names_survive_disk(self, tmp_path):
        p = tmp_path / "profiles.json"
        store.save_profiles([Profile(name="کلیک سریع")], p)
        assert store.load_profiles(p)[0].name == "کلیک سریع"


class TestStorageLocation:
    def test_development_storage_is_inside_the_project(self):
        """A development run must not write into a real user's %APPDATA%."""
        assert not store.is_frozen()
        assert "autoclicker" in str(store.data_dir())

    def test_storage_note_names_the_kind_and_the_path(self):
        note = store.storage_note()
        assert "development" in note
        assert str(store.data_dir()) in note


class TestHotkeyParsing:
    """
    Parsing only. Registration needs the Windows API, but every interesting mistake - a modifier
    without a key, two keys, an unknown key name - is a parsing question and is settled here.
    """

    def test_a_function_key(self):
        from autoclick.ui.hotkeys import parse_hotkey

        mods, vk = parse_hotkey("f6")
        assert mods == 0
        assert vk == 0x75

    def test_modifiers_combine(self):
        from autoclick.ui.hotkeys import parse_hotkey

        mods, vk = parse_hotkey("ctrl+shift+f6")
        assert mods == 0x0002 | 0x0004
        assert vk == 0x75

    def test_case_and_spacing_do_not_matter(self):
        from autoclick.ui.hotkeys import parse_hotkey

        assert parse_hotkey("  CTRL + Shift + F6 ") == parse_hotkey("ctrl+shift+f6")

    @pytest.mark.parametrize("bad", ["", "   ", "ctrl+alt", "shift", "nonsense"])
    def test_unusable_specs_are_rejected(self, bad):
        from autoclick.ui.hotkeys import parse_hotkey

        with pytest.raises(ValueError):
            parse_hotkey(bad)

    def test_two_keys_are_rejected(self):
        """
        A hotkey is modifiers plus ONE key. Accepting two would silently ignore the second, and the
        user would think they had registered a combination they had not.
        """
        from autoclick.ui.hotkeys import parse_hotkey

        with pytest.raises(ValueError) as e:
            parse_hotkey("ctrl+a+b")
        assert "one" in str(e.value).lower()

    def test_off_windows_registration_reports_unavailable(self):
        from autoclick.ui.hotkeys import Hotkey

        if sys.platform == "win32":
            pytest.skip("this asserts the non-Windows behaviour")
        h = Hotkey(lambda: None)
        assert h.register("f6") is False
        assert "Windows" in h.error
        # and unregistering must be safe to call anyway
        h.unregister()


class TestEngineSafety:
    """The invariants that keep the program from doing something harmful."""

    def test_advanced_mode_with_no_steps_is_refused(self):
        with pytest.raises(ProfileError):
            Profile(mode="advanced", steps=[]).compile_steps()

    def test_at_once_is_bounded(self):
        with pytest.raises(ProfileError):
            Profile(at_once=0).validate()
        with pytest.raises(ProfileError):
            Profile(at_once=101).validate()

    def test_interval_is_bounded(self):
        with pytest.raises(ProfileError):
            Profile(interval_ms=-1).validate()
        with pytest.raises(ProfileError):
            Profile(interval_ms=48 * 3600 * 1000).validate()

    def test_a_key_step_with_no_keys_is_refused(self):
        with pytest.raises(ProfileError):
            KeyStep(keys=[]).validate()

    def test_fixed_position_requires_sane_coordinates(self):
        # enormous values are rejected; negative ones are legal on a left-hand monitor
        ClickStep(position="fixed", x=-1920, y=0).validate()
        with pytest.raises(ProfileError):
            ClickStep(position="fixed", x=999_999, y=0).validate()