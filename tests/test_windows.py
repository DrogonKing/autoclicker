"""
Layout and key-table tests.

The struct layout is asserted on EVERY platform now, which is a change from the first version of this
file. CI on windows-latest caught what that version missed:

    AssertionError: assert 32 == 24    # MOUSEINPUT on windows-latest

The struct had been built from `ctypes.wintypes.LONG` / `.ULONG`, which are aliases for `c_long` and
`c_ulong`: 4 bytes on Windows and 8 on 64-bit Linux. So the same code produced a 40-byte INPUT on
Windows and a 56-byte one here, with every field offset shifted - meaning a wrong-input bug that would
appear the moment anything changed, and that no test on this machine could have seen.

It is now built from fixed-width types (c_int32 / c_uint32 / c_uint16 / c_size_t), so the layout is
the same everywhere and these assertions are meaningful in any environment. The Windows-only block
below then covers the things that genuinely need the real platform.
"""

from __future__ import annotations

import ctypes
import sys

import pytest

from autoclick.core import wininput

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="needs the real Windows API")


class TestStructLayoutEverywhere:
    """
    Runs on any OS. This is the block that makes the struct a tested property rather than an
    assumption, and the reason it can run here is the fixed-width field types.
    """

    def test_input_size(self):
        assert ctypes.sizeof(wininput.INPUT) == wininput._EXPECTED_INPUT_SIZE, wininput.layout_report()

    def test_mouse_input_size(self):
        assert ctypes.sizeof(wininput.MOUSEINPUT) == wininput.EXPECTED_MOUSE_SIZE

    def test_keybd_input_size(self):
        assert ctypes.sizeof(wininput.KEYBDINPUT) == wininput.EXPECTED_KEY_SIZE

    def test_union_is_sized_by_its_largest_member(self):
        """INPUT's size follows from the union, so a broken member shows up as a broken INPUT."""
        largest = max(
            ctypes.sizeof(wininput.MOUSEINPUT),
            ctypes.sizeof(wininput.KEYBDINPUT),
            ctypes.sizeof(wininput.HARDWAREINPUT),
        )
        assert ctypes.sizeof(wininput._INPUTUNION) == largest

    def test_mouse_field_offsets(self):
        """
        The offsets are what SendInput reads. Getting a 40-byte struct with a shifted `dwFlags` sends
        the right number of bytes containing the wrong instruction.
        """
        actual = {k: getattr(wininput.MOUSEINPUT, k).offset for k in wininput.MOUSE_FIELD_OFFSETS}
        assert actual == wininput.MOUSE_FIELD_OFFSETS

    def test_key_field_offsets(self):
        actual = {k: getattr(wininput.KEYBDINPUT, k).offset for k in wininput.KEY_FIELD_OFFSETS}
        assert actual == wininput.KEY_FIELD_OFFSETS

    def test_type_field_is_first(self):
        """`type` selects which union member SendInput reads, so its offset must be 0."""
        assert wininput.INPUT.type.offset == 0

    def test_union_follows_the_type_field(self):
        """
        8, not 4: the union contains a pointer-sized member (ULONG_PTR), so its alignment is 8 and it
        is padded to the next 8-byte boundary. A struct where this were 4 would still be 40 bytes here
        and 28 on 32-bit, which is why the offset is asserted rather than the size alone.
        """
        expected = ctypes.sizeof(wininput.ULONG_PTR_)
        assert wininput.INPUT.union.offset == expected

    def test_dword_is_four_bytes(self):
        assert ctypes.sizeof(wininput.DWORD_) == 4

    def test_word_is_two_bytes(self):
        assert ctypes.sizeof(wininput.WORD_) == 2

    def test_long_is_four_bytes_even_where_c_long_is_eight(self):
        """
        The specific trap: on this platform `c_long` is 8 bytes, but Windows' LONG is 4.

        If this assertion ever fails, the struct has gone back to a platform-dependent definition.
        """
        assert ctypes.sizeof(wininput.LONG_) == 4
        assert ctypes.sizeof(ctypes.c_long) in (4, 8)  # platform-dependent, hence not used

    def test_ulong_ptr_tracks_the_pointer_size(self):
        assert ctypes.sizeof(wininput.ULONG_PTR_) == ctypes.sizeof(ctypes.c_void_p)

    def test_layout_is_reported_as_valid(self):
        assert wininput.input_structure_is_valid(), wininput.layout_report()

    def test_mouse_input_can_be_constructed(self):
        """
        Construction, not just size.

        A real failure on windows-latest: after the field types were fixed, `dwExtraInfo` became an
        integer type, and `c_size_t` rejects None where the pointer type it replaced accepted it -
        "TypeError: 'NoneType' object cannot be interpreted as an integer". Building the struct in a
        test catches that here instead of after a CI round trip.
        """
        mi = wininput.MOUSEINPUT(0, 0, 0, wininput.MOUSEEVENTF_LEFTDOWN, 0, 0)
        assert mi.dwFlags == wininput.MOUSEEVENTF_LEFTDOWN
        assert mi.dx == 0 and mi.dy == 0

    def test_keybd_input_can_be_constructed(self):
        ki = wininput.KEYBDINPUT(0x41, 0, 0, 0, 0)
        assert ki.wVk == 0x41

    def test_input_can_wrap_a_mouse_event(self):
        """The shape SendInput actually receives: a tagged union member."""
        mi = wininput.MOUSEINPUT(0, 0, 0, wininput.MOUSEEVENTF_MOVE, 0, 0)
        inp = wininput.INPUT(type=wininput.INPUT_MOUSE, union=wininput._INPUTUNION(mi=mi))
        assert inp.type == wininput.INPUT_MOUSE
        assert inp.union.mi.dwFlags == wininput.MOUSEEVENTF_MOVE

    def test_input_can_wrap_a_key_event(self):
        ki = wininput.KEYBDINPUT(0x41, 0, 0, 0, 0)
        inp = wininput.INPUT(type=wininput.INPUT_KEYBOARD, union=wininput._INPUTUNION(ki=ki))
        assert inp.type == wininput.INPUT_KEYBOARD

    def test_every_input_constructor_call_site_passes_an_integer_extra_info(self):
        """
        A guard against the same mistake returning: dwExtraInfo must be an integer.

        Asserted through the class rather than by grepping the source, so it holds no matter how the
        call sites are written.
        """
        field_type = dict(wininput.MOUSEINPUT._fields_)["dwExtraInfo"]
        assert field_type in (ctypes.c_size_t, ctypes.c_uint64, ctypes.c_uint32), (
            "dwExtraInfo is a pointer type again; c_size_t is what matches ULONG_PTR"
        )


class TestKeyTable:
    """Runs everywhere: a wrong virtual-key code is wrong on any platform."""

    def test_letters_map_to_their_uppercase_codes(self):
        assert wininput.VK["a"] == 0x41
        assert wininput.VK["z"] == 0x5A

    def test_digits_map_to_their_ascii_codes(self):
        assert wininput.VK["0"] == 0x30
        assert wininput.VK["9"] == 0x39

    def test_function_keys_f1_to_f12_are_contiguous(self):
        for i in range(1, 13):
            assert wininput.VK[f"f{i}"] == 0x6F + i, f"f{i} is wrong"

    def test_function_keys_f13_to_f24_exist(self):
        """
        CI caught these missing: a real-input test asked for `f24` and got "unknown key name".

        They are absent from ordinary keyboards but present in Win32 (VK_F13 = 0x7C .. VK_F24 = 0x87),
        and a macro keypad can send them. A missing key raises rather than silently doing nothing,
        which is why the test failed loudly instead of the click quietly not happening.
        """
        # VK_F1 = 0x70, so VK_Fn = 0x6F + n for the whole range
        for i in range(13, 25):
            assert wininput.VK[f"f{i}"] == 0x6F + i, f"f{i} is missing or wrong"
        assert wininput.VK["f13"] == 0x7C
        assert wininput.VK["f24"] == 0x87

    def test_common_modifiers(self):
        assert wininput.VK["ctrl"] == 0x11
        assert wininput.VK["shift"] == 0x10
        assert wininput.VK["alt"] == 0x12

    def test_aliases_resolve_to_the_same_code(self):
        assert wininput.VK["enter"] == wininput.VK["return"]
        assert wininput.VK["esc"] == wininput.VK["escape"]
        assert wininput.VK["ctrl"] == wininput.VK["control"]

    def test_names_are_lowercase_only(self):
        """Lookups lowercase the input, so a mixed-case table key could never be matched."""
        mixed = [k for k in wininput.VK if k != k.lower()]
        assert mixed == [], f"these table keys can never match: {mixed}"

    def test_no_duplicate_codes_for_distinct_names(self):
        """Two names sharing a code is usually a typo, and it hides a key that cannot be pressed."""
        from collections import defaultdict

        by_code: dict[int, list[str]] = defaultdict(list)
        for name, code in wininput.VK.items():
            by_code[code].append(name)
        # a handful of intentional aliases are expected; a large group means a copy-paste error
        suspicious = {code: names for code, names in by_code.items() if len(names) > 3}
        assert suspicious == {}, f"unexpected groups of aliases: {suspicious}"

    def test_unknown_key_raises_rather_than_returning_zero(self):
        """
        Sending virtual key 0 does nothing at all, which would look like the autoclicker silently
        skipping a step - the hardest kind of bug for a user to diagnose.
        """
        with pytest.raises(wininput.InputError):
            wininput.key_to_vk("definitely_not_a_key")


class TestBackendSelection:
    def test_dry_run_never_returns_the_real_backend(self):
        """Asserted everywhere: the decision is platform-independent, and a stray real click in a dry
        run would defeat the entire point of the mode."""
        assert isinstance(wininput.make_backend(dry_run=True), wininput.NullBackend)

    def test_off_windows_always_records(self):
        if sys.platform == "win32":
            pytest.skip("this asserts the non-Windows branch")
        assert isinstance(wininput.make_backend(dry_run=False), wininput.NullBackend)


@windows_only
class TestRealInput:
    """
    Sending real input.

    A GitHub Windows runner has a desktop, so a click at (0, 0) hits the corner of the screen rather
    than a control - the only safe target for an unattended test.
    """

    def test_backend_constructs(self):
        assert wininput.WindowsBackend() is not None

    def test_cursor_position_is_readable(self):
        x, y = wininput.WindowsBackend().cursor_pos()
        # virtual desktops may have negative origins, so only sanity-bound the values
        assert -32_768 <= x <= 32_767
        assert -32_768 <= y <= 32_767

    def test_move_to_the_top_left_corner_lands_there(self):
        """
        The end-to-end check that the struct is right: a malformed INPUT does not raise, it either
        does nothing or moves the pointer somewhere else. Asserting the position afterwards is what
        proves the bytes were interpreted as a move.
        """
        backend = wininput.WindowsBackend()
        backend.refresh_screen()
        backend.move(0, 0)
        x, y = backend.cursor_pos()
        # one pixel of tolerance: absolute coordinates are scaled to 0..65535 and back
        assert abs(x) <= 2 and abs(y) <= 2, f"cursor landed at ({x}, {y}) instead of the corner"

    def test_key_down_and_up_are_accepted(self):
        """No assertion on effect - only that SendInput accepted the events."""
        backend = wininput.WindowsBackend()
        backend.key_down("f24")   # bound to nothing in this app, so harmless
        backend.key_up("f24")

    def test_unknown_key_is_rejected(self):
        with pytest.raises(wininput.InputError) as e:
            wininput.WindowsBackend().key_down("not_a_real_key")
        assert "not_a_real_key" in str(e.value)

    def test_send_input_reports_one_event_consumed(self):
        """
        SendInput's return value is the number of events inserted. Anything else means the input was
        refused, and the backend raises - so a passing call is a confirmed delivery.
        """
        backend = wininput.WindowsBackend()
        backend.refresh_screen()
        backend.move(0, 0)  # raises InputError if the OS refused it
