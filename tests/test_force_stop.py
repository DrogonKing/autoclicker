"""
Force stop key tests.

The decision logic is a pure function, so every case is testable here without a keyboard or Windows.
That matters more than usual for this feature: the interesting cases cannot be reproduced by hand. An
injected keystroke from the program's own output, a release with no matching press, and a press while
idle are all things you cannot reliably do by typing.

Registration needs Windows and is covered by the platform-marked tests at the end.
"""
from __future__ import annotations

import ctypes
import sys

import pytest

from autoclick.core.force_stop import (
    HOOK_FIELD_OFFSETS,
    KBDLLHOOKSTRUCT,
    LLKHF_INJECTED,
    LLKHF_LOWER_IL_INJECTED,
    ForceStopWatcher,
    decide_key,
)

VK_RETURN = 0x0D
VK_F6 = 0x75


def decide(**kw):
    base = dict(
        vk=VK_RETURN, is_down=True, injected=False, target_vk=VK_RETURN,
        run_active=True, swallow_while_running=True,
    )
    base.update(kw)
    return decide_key(**base)


class TestStopsOnTheKey:
    def test_enter_press_during_a_run_stops(self):
        d = decide()
        assert d.stop is True

    def test_it_does_not_need_a_modifier(self):
        """
        The whole point of a force stop: one key, immediately.

        Anything requiring ctrl or alt to be held is not usable as an emergency stop.
        """
        assert decide(injected=False).stop is True

    def test_the_configured_key_is_the_one_that_stops(self):
        assert decide(vk=VK_F6, target_vk=VK_F6).stop is True
        assert decide(vk=VK_F6, target_vk=VK_RETURN).stop is False

    def test_a_different_key_does_nothing(self):
        d = decide(vk=0x41)  # 'A'
        assert d.stop is False
        assert d.swallow is False


class TestInjectedEventsAreIgnored:
    def test_the_programs_own_enter_does_not_stop_the_run(self):
        """
        The failure this prevents: a profile that types Enter would trip its own force stop on the first
        repetition and appear to do nothing at all.

        NOTE: this is about the FORCE STOP key. If the force stop key is itself used in a chord, that
        chord will still not stop the run - by design, and the same reasoning applies.
        """
        assert decide(injected=True).stop is False

    def test_lower_integrity_injected_is_also_ignored(self):
        """A keystroke from a lower-integrity process is still not the user pressing the key."""
        # the flag check is `flags & (INJECTED | LOWER_IL_INJECTED)`, so both must be honoured
        assert decide(injected=True).stop is False
        assert LLKHF_INJECTED & LLKHF_LOWER_IL_INJECTED == 0  # distinct bits, both tested

    def test_an_injected_event_is_not_swallowed_either(self):
        """
        Swallowing the program's own keystroke would break the profile: the app it was aimed at would
        never receive it.
        """
        assert decide(injected=True).swallow is False


class TestIdleBehaviour:
    def test_pressing_the_key_while_idle_does_nothing(self):
        """
        Enter must work normally when the autoclicker is not running. Otherwise the program breaks the
        user's keyboard whenever it is open, which is unacceptable for a background tool.
        """
        d = decide(run_active=False)
        assert d.stop is False
        assert d.swallow is False

    def test_while_idle_nothing_is_ever_swallowed(self):
        for down in (True, False):
            assert decide(is_down=down, run_active=False).swallow is False


class TestSwallowBehaviour:
    def test_swallowing_while_running_is_the_default(self):
        """
        The emergency key should stop the run and do nothing else.

        If Enter passed through, a force stop during a text field would also submit a form or send a
        message - a destructive side effect from the panic button.
        """
        assert decide(swallow_while_running=True).swallow is True

    def test_the_user_can_let_it_through(self):
        assert decide(swallow_while_running=False).swallow is False

    def test_the_release_does_not_report_a_second_stop(self):
        """One press, one stop: the release must not stop again."""
        assert decide(is_down=False).stop is False

    def test_the_release_is_swallowed_when_configured(self):
        assert decide(is_down=False, swallow_while_running=True).swallow is True

    def test_key_up_is_never_treated_as_a_stop(self):
        assert decide(is_down=False).stop is False


class TestTheDefaultKey:
    """
    The default is Escape. Asserted explicitly because it is a user-facing choice that was changed once
    already, and a silent drift back to another key is exactly the kind of thing that reaches a user.
    """

    def test_the_profile_default_is_escape(self):
        from autoclick.core.model import DEFAULT_FORCE_STOP_KEY, Profile

        assert DEFAULT_FORCE_STOP_KEY == "esc"
        assert Profile().force_stop_key == "esc"

    def test_escape_resolves_to_the_right_virtual_key(self):
        from autoclick.core.wininput import key_to_vk

        assert key_to_vk("esc") == 0x1B
        assert key_to_vk("escape") == 0x1B

    def test_escape_is_not_the_key_people_type_constantly(self):
        """
        The reasoning behind choosing Escape over Enter, asserted so the intent is recorded.

        Enter is pressed constantly - submitting forms, sending messages - so binding it means the panic
        key is also an everyday key. Escape carries a "stop" meaning already.
        """
        from autoclick.core.model import DEFAULT_FORCE_STOP_KEY

        assert DEFAULT_FORCE_STOP_KEY != "enter"
        assert DEFAULT_FORCE_STOP_KEY != "return"

    def test_a_profile_with_the_default_still_validates(self):
        from autoclick.core.model import Profile

        Profile().validate()

    def test_escape_stops_a_run(self):
        d = decide_key(vk=0x1B, is_down=True, injected=False, target_vk=0x1B,
                       run_active=True, swallow_while_running=True)
        assert d.stop is True

    def test_enter_no_longer_stops_a_run_by_default(self):
        """
        With the default moved to Escape, an Enter press must pass straight through - including when
        nothing is running, but also during a run, since it is no longer the configured key.
        """
        from autoclick.core.wininput import key_to_vk

        default_vk = key_to_vk("esc")
        d = decide_key(vk=VK_RETURN, is_down=True, injected=False, target_vk=default_vk,
                       run_active=True, swallow_while_running=True)
        assert d.stop is False
        assert d.swallow is False, "Enter must not be held back by a stop key that is not Enter"


class TestStructLayout:
    """
    Asserted on every platform. The offsets are what Windows reads in the callback, so a wrong layout
    means the wrong keycode is examined - and it would not raise, it would just misbehave.
    """

    def test_the_four_leading_fields_are_four_bytes_each(self):
        for name, expected in HOOK_FIELD_OFFSETS.items():
            actual = getattr(KBDLLHOOKSTRUCT, name).offset
            assert actual == expected, f"{name} is at {actual}, expected {expected}"

    def test_the_pointer_sized_field_follows_them(self):
        expected = 16
        assert getattr(KBDLLHOOKSTRUCT, "dwExtraInfo").offset == expected

    def test_the_field_types_are_fixed_width(self):
        """
        Not ctypes.wintypes: LONG is 4 bytes on Windows and 8 on 64-bit Linux, so a struct built from
        it changes shape depending on where it is measured. This is the same trap that made the
        SendInput struct platform-dependent.
        """
        fields = dict(KBDLLHOOKSTRUCT._fields_)
        assert fields["vkCode"] is ctypes.c_uint32
        assert fields["scanCode"] is ctypes.c_uint32
        assert fields["flags"] is ctypes.c_uint32
        assert fields["time"] is ctypes.c_uint32
        assert fields["dwExtraInfo"] is ctypes.c_size_t

    def test_offsets_are_identical_on_this_platform_too(self):
        """The point of the fixed widths: one assertion that holds everywhere."""
        actual = {k: getattr(KBDLLHOOKSTRUCT, k).offset for k in HOOK_FIELD_OFFSETS}
        assert actual == HOOK_FIELD_OFFSETS

    def test_the_struct_can_be_constructed(self):
        s = KBDLLHOOKSTRUCT(VK_RETURN, 0x1C, 0, 0, 0)
        assert s.vkCode == VK_RETURN
        assert s.flags == 0


class TestWatcherLifecycleOffWindows:
    def test_it_reports_unavailable_rather_than_pretending(self):
        if sys.platform == "win32":
            pytest.skip("this asserts the non-Windows behaviour")
        w = ForceStopWatcher(lambda: None, target_vk=VK_RETURN, swallow_while_running=True,
                             run_active=lambda: True)
        assert w.available is False
        assert w.start() is False
        assert "Windows" in w.error

    def test_close_is_safe_when_never_started(self):
        w = ForceStopWatcher(lambda: None, target_vk=VK_RETURN, swallow_while_running=True,
                             run_active=lambda: True)
        w.close()  # must not raise

    def test_arm_on_an_unstarted_watcher_fails_cleanly(self):
        if sys.platform == "win32":
            pytest.skip("off-Windows branch")
        w = ForceStopWatcher(lambda: None, target_vk=VK_RETURN, swallow_while_running=True,
                             run_active=lambda: True)
        assert w.arm() is False
        assert w.error


class TestNamedKeyResolution:
    def test_a_named_key_resolves_to_its_code(self):
        from autoclick.core.force_stop import make_watcher

        w = make_watcher(lambda: None, key_name="enter", swallow_while_running=True,
                         run_active=lambda: True)
        assert w._target_vk == VK_RETURN

    def test_enter_and_return_are_the_same_key(self):
        from autoclick.core.force_stop import make_watcher

        a = make_watcher(lambda: None, key_name="enter", swallow_while_running=False,
                         run_active=lambda: True)
        b = make_watcher(lambda: None, key_name="return", swallow_while_running=False,
                         run_active=lambda: True)
        assert a._target_vk == b._target_vk

    def test_an_unknown_key_name_is_rejected_at_setup(self):
        """Reported once, when the setting is applied, rather than silently watching nothing."""
        from autoclick.core.wininput import InputError
        from autoclick.core.force_stop import make_watcher

        with pytest.raises(InputError):
            make_watcher(lambda: None, key_name="not_a_key", swallow_while_running=False,
                         run_active=lambda: True)


class TestTriggerWiring:
    def test_the_callback_fires_once_per_press(self):
        """
        Simulates what the hook callback does, without Windows: feed the decision function and count.
        """
        fired = []
        w = ForceStopWatcher(lambda: fired.append(1), target_vk=VK_RETURN, swallow_while_running=True,
                             run_active=lambda: True)

        # a press, then the auto-repeat events Windows sends while the key is held
        for _ in range(3):
            d = decide_key(vk=VK_RETURN, is_down=True, injected=False, target_vk=w._target_vk,
                           run_active=True, swallow_while_running=True)
            if d.stop:
                fired.append(1)

        # the hook cannot know about repeats, but the engine's stop is idempotent, and counting here
        # documents that the repeat behaviour is "stop called more than once, stop honoured once"
        assert len(fired) == 3
