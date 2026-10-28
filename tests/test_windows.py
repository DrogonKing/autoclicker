"""
Windows-only checks.

These are skipped everywhere else, and they are the reason CI runs on windows-latest: the SendInput
structure layout and the virtual-key table cannot be verified on the machine this code was written
on, but they can be verified on a Windows runner before anything is published.

A wrong struct layout does not raise an error. It sends malformed input, which means clicks land in
the wrong place or not at all - exactly the class of bug that must be caught by CI rather than
reported by a user.
"""

from __future__ import annotations

import ctypes
import sys

import pytest

from autoclick.core import wininput

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only check")


@windows_only
class TestStructLayout:
    def test_input_struct_matches_the_win32_headers(self):
        expected = (
            wininput.WINDOWS_INPUT_SIZE_64
            if ctypes.sizeof(ctypes.c_void_p) == 8
            else wininput.WINDOWS_INPUT_SIZE_32
        )
        assert ctypes.sizeof(wininput.INPUT) == expected, (
            f"INPUT is {ctypes.sizeof(wininput.INPUT)} bytes, headers say {expected}. "
            "SendInput would receive malformed input."
        )

    def test_mouse_input_is_24_bytes_on_64_bit(self):
        """The union is sized by its largest member, so MOUSEINPUT's size is what sets INPUT's."""
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            pytest.skip("32-bit layout differs; the INPUT assertion above covers it")
        assert ctypes.sizeof(wininput.MOUSEINPUT) == 24

    def test_keybd_input_is_24_bytes_on_64_bit(self):
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            pytest.skip("32-bit layout differs")
        assert ctypes.sizeof(wininput.KEYBDINPUT) == 24

    def test_layout_report_is_clean(self):
        assert wininput.input_structure_is_valid(), wininput.layout_report()


@windows_only
class TestRealInput:
    """
    Sending real input on a CI runner.

    A headless Windows runner has a desktop (unlike Linux CI, which needs Xvfb), so a click to
    (0, 0) is safe: it hits the corner of the screen, not a control. The assertion is that SendInput
    reports one event consumed, which is the only honest way to prove the call works.
    """

    def test_backend_constructs(self):
        backend = wininput.WindowsBackend()
        assert backend is not None

    def test_cursor_position_is_readable(self):
        backend = wininput.WindowsBackend()
        x, y = backend.cursor_pos()
        # virtual desktops can have negative origins, so only sanity-bound the values
        assert -32_768 <= x <= 32_767
        assert -32_768 <= y <= 32_767

    def test_move_to_the_top_left_corner_succeeds(self):
        """(0,0) is the safest target: the screen corner, away from any control."""
        backend = wininput.WindowsBackend()
        backend.move(0, 0)
        x, y = backend.cursor_pos()
        # allow one pixel of rounding, since absolute coordinates are scaled to 0..65535
        assert abs(x) <= 1 and abs(y) <= 1, f"cursor landed at ({x}, {y}) instead of the corner"

    def test_key_down_and_up_do_not_raise(self):
        """No assertion on effect - only that SendInput accepted the events."""
        backend = wininput.WindowsBackend()
        backend.key_down("f24")   # a key nothing binds, so pressing it is harmless
        backend.key_up("f24")

    def test_unknown_key_is_rejected_with_a_message(self):
        backend = wininput.WindowsBackend()
        with pytest.raises(wininput.InputError) as e:
            backend.key_down("not_a_real_key")
        assert "not_a_real_key" in str(e.value)


class TestKeyTable:
    """The virtual-key table is checked everywhere: a wrong code is a wrong code on any platform."""

    def test_letters_map_to_their_uppercase_codes(self):
        assert wininput.VK["a"] == 0x41
        assert wininput.VK["z"] == 0x5A

    def test_digits_map_to_their_ascii_codes(self):
        assert wininput.VK["0"] == 0x30
        assert wininput.VK["9"] == 0x39

    def test_function_keys_are_contiguous(self):
        for i in range(1, 13):
            assert wininput.VK[f"f{i}"] == 0x6F + i, f"f{i} is wrong"

    def test_common_modifiers(self):
        assert wininput.VK["ctrl"] == 0x11
        assert wininput.VK["shift"] == 0x10
        assert wininput.VK["alt"] == 0x12

    def test_aliases_resolve_to_the_same_code(self):
        assert wininput.VK["enter"] == wininput.VK["return"]
        assert wininput.VK["esc"] == wininput.VK["escape"]
        assert wininput.VK["ctrl"] == wininput.VK["control"]

    def test_names_are_lowercase_only(self):
        """A mixed-case key in the table would never match, since lookups lowercase the input."""
        mixed = [k for k in wininput.VK if k != k.lower()]
        assert mixed == [], f"these table keys can never be matched: {mixed}"

    def test_unknown_key_raises_rather_than_returning_zero(self):
        """
        Sending virtual key 0 does nothing at all.

        That would look like the autoclicker silently skipping a step, which is the hardest kind of
        bug for a user to diagnose.
        """
        with pytest.raises(wininput.InputError):
            wininput.key_to_vk("definitely_not_a_key")


class TestBackendSelection:
    def test_dry_run_never_returns_the_real_backend(self):
        """
        The guard that matters: a dry run must not send a single real click.

        This is asserted on every platform because the decision is platform-independent.
        """
        backend = wininput.make_backend(dry_run=True)
        assert isinstance(backend, wininput.NullBackend)

    def test_off_windows_always_records(self):
        if sys.platform == "win32":
            pytest.skip("this is the non-Windows branch")
        assert isinstance(wininput.make_backend(dry_run=False), wininput.NullBackend)
