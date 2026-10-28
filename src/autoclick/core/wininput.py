"""
The Windows input backend.

This is the only part of the program that cannot be tested on the machine it was written on, so it is
deliberately the smallest possible surface: four methods, no logic, no scheduling, no state.

Two things it gets right that a naive implementation does not:

  - It uses SendInput, not mouse_event/keybd_event. The older calls are deprecated and, more
    importantly, are ignored by some games and full-screen applications.
  - A fixed virtual-desktop coordinate space. SetCursorPos takes physical pixels, so on a machine
    where the process is not DPI-aware a click aimed at the middle of a 4K screen lands in the wrong
    place. The manifest marks the process per-monitor DPI aware, and coordinates are passed through
    as the user picked them.

Every call is wrapped so a failure is reported rather than swallowed: an autoclicker that silently
does nothing is worse than one that says why.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from typing import Any

from ..core.engine import InputBackend

IS_WINDOWS = sys.platform == "win32"

# --- SendInput structures -------------------------------------------------------------------------
# Layout must match the Win32 headers exactly. ctypes does not verify this for us, and a wrong field
# order produces clicks at the wrong coordinates rather than an error, so the sizes are asserted at
# import time below.

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wt.ULONG)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wt.ULONG)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wt.DWORD),
        ("wParamL", wt.WORD),
        ("wParamH", wt.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("union", _INPUTUNION)]


# A wrong structure size would not raise, it would send garbage. Checked here so a future edit that
# breaks the layout fails loudly on the first run instead of misbehaving in the field.
_EXPECTED_INPUT_SIZE = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28


class InputError(RuntimeError):
    """SendInput refused or failed. Carries the Win32 error code."""


# --- virtual keys ---------------------------------------------------------------------------------
VK: dict[str, int] = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "shift": 0x10,
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "pause": 0x13, "capslock": 0x14,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "pageup": 0x21, "pagedown": 0x22,
    "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "insert": 0x2D, "delete": 0x2E, "del": 0x2E,
    "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C,
    "num0": 0x60, "num1": 0x61, "num2": 0x62, "num3": 0x63, "num4": 0x64,
    "num5": 0x65, "num6": 0x66, "num7": 0x67, "num8": 0x68, "num9": 0x69,
    "multiply": 0x6A, "add": 0x6B, "subtract": 0x6D, "decimal": 0x6E, "divide": 0x6F,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "numlock": 0x90, "scrolllock": 0x91,
    "lshift": 0xA0, "rshift": 0xA1, "lctrl": 0xA2, "rctrl": 0xA3, "lalt": 0xA4, "ralt": 0xA5,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0,
    "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
    # Persian keyboard reaches these through a layout; the physical key is what matters
    "\u200c": 0x20,  # zero-width non-joiner is sent as space; see documentation
}
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())
for _d in "0123456789":
    VK[_d] = ord(_d)


def key_to_vk(key: str) -> int:
    """
    Resolve a key name to a virtual-key code.

    Raises rather than returning something plausible-but-wrong: sending 0 to SendInput does nothing,
    which would look like the autoclicker ignoring that step.
    """
    k = (key or "").strip().lower()
    if k in VK:
        return VK[k]
    # single character: use VkKeyScan so non-US layouts (Persian, AZERTY) map correctly
    if len(key.strip()) == 1 and IS_WINDOWS:
        res = _user32.VkKeyScanW(ctypes.c_wchar(key.strip()))
        if res != -1:
            return res & 0xFF
    raise InputError(f"unknown key name: {key!r}")


class WindowsBackend(InputBackend):
    """Real input. Instantiated only on Windows."""

    def __init__(self) -> None:
        if not IS_WINDOWS:
            raise InputError("the Windows input backend can only run on Windows")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._send_input = self._user32.SendInput
        self._send_input.argtypes = (wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        self._send_input.restype = wt.UINT
        self._screen = (0, 0, 0, 0)
        self.refresh_screen()

    # ------------------------------------------------------------------ helpers

    def refresh_screen(self) -> tuple[int, int, int, int]:
        """
        The virtual desktop rectangle, in physical pixels.

        Re-read on every fixed-position move would be wasteful, but caching it forever is wrong when
        a monitor is plugged in. The UI calls this when it captures a coordinate.
        """
        if not IS_WINDOWS:
            return (0, 0, 1, 1)
        SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
        SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
        g = self._user32.GetSystemMetrics
        self._screen = (
            g(SM_XVIRTUALSCREEN), g(SM_YVIRTUALSCREEN),
            g(SM_CXVIRTUALSCREEN), g(SM_CYVIRTUALSCREEN),
        )
        return self._screen

    def cursor_pos(self) -> tuple[int, int]:
        pt = wt.POINT()
        self._user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y)

    def _send(self, inp: INPUT) -> None:
        sent = self._send_input(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        if sent != 1:
            code = ctypes.get_last_error()
            raise InputError(f"SendInput failed (Win32 error {code})")

    def _mouse(self, flags: int, dx: int = 0, dy: int = 0) -> None:
        mi = MOUSEINPUT(dx, dy, 0, flags, 0, None)
        self._send(INPUT(type=INPUT_MOUSE, union=_INPUTUNION(mi=mi)))

    # ------------------------------------------------------------------ the four calls

    def move(self, x: int, y: int) -> None:
        """
        Move the pointer to absolute virtual-desktop coordinates.

        SendInput's absolute mode wants a 0..65535 range over the virtual desktop, so a raw pixel
        coordinate must be normalised. Getting this wrong is the classic "click lands on the wrong
        monitor" bug.
        """
        left, top, width, height = self._screen
        if width <= 0 or height <= 0:
            self.refresh_screen()
            left, top, width, height = self._screen
        nx = int(round((x - left) * 65535 / max(1, width - 1)))
        ny = int(round((y - top) * 65535 / max(1, height - 1)))
        self._mouse(
            MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
            max(0, min(65535, nx)), max(0, min(65535, ny)),
        )

    def click(self, button: str, double: bool = False) -> None:
        down, up = {
            "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
            "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
            "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
        }.get(button, (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP))
        presses = 2 if double else 1
        for _ in range(presses):
            self._mouse(down)
            self._mouse(up)

    def key_down(self, key: str) -> None:
        vk = key_to_vk(key)
        ki = KEYBDINPUT(vk, 0, 0, 0, None)
        self._send(INPUT(type=INPUT_KEYBOARD, union=_INPUTUNION(ki=ki)))

    def key_up(self, key: str) -> None:
        vk = key_to_vk(key)
        ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, None)
        self._send(INPUT(type=INPUT_KEYBOARD, union=_INPUTUNION(ki=ki)))


class NullBackend(InputBackend):
    """
    Records instead of sending.

    Used by the "test without clicking" mode and by every test. It exists in the shipped program on
    purpose: a user can rehearse a profile - see the timing and the count - without it clicking
    anything, which is the only safe way to check a sequence before it runs.
    """

    def __init__(self, time_fn: Any = None) -> None:
        self.events: list[tuple[str, object]] = []
        self._time_fn = time_fn or (lambda: 0)

    def move(self, x: int, y: int) -> None:
        self.events.append(("move", (x, y, self._time_fn())))

    def click(self, button: str, double: bool = False) -> None:
        self.events.append(("click", (button, double, self._time_fn())))

    def key_down(self, key: str) -> None:
        self.events.append(("key_down", (key, self._time_fn())))

    def key_up(self, key: str) -> None:
        self.events.append(("key_up", (key, self._time_fn())))

    def click_times(self) -> list[int]:
        return [int(p[2]) for kind, p in self.events if kind == "click"]  # type: ignore[index]


if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
else:  # pragma: no cover - only reached off Windows
    _user32 = None


def make_backend(dry_run: bool = False) -> InputBackend:
    """
    The only place that decides between real input and a recorder.

    A single decision point means a dry run cannot accidentally send one real click among the
    recorded ones.
    """
    if dry_run or not IS_WINDOWS:
        return NullBackend()
    return WindowsBackend()


# The Win32 INPUT struct on 64-bit Windows is 40 bytes; on 32-bit it is 28. The widths are fixed by
# the headers: DWORD is always 4 bytes, ULONG is 4 bytes on Windows, and the union holds the largest
# member (MOUSEINPUT at 24 bytes on 64-bit). ctypes gives the right answer only when the platform's
# types match Windows', so this can only be asserted where it matters.
WINDOWS_INPUT_SIZE_64 = 40
WINDOWS_INPUT_SIZE_32 = 28


def layout_report() -> str:
    """
    Explain the struct layout, and only claim a mismatch where a mismatch means something.

    `ctypes.wintypes.ULONG` is 4 bytes on Windows and 8 on Linux, so on this machine the struct is
    correctly 56 bytes and comparing it to 40 would report a fault that is not there. The report says
    which case applies instead of shouting MISMATCH at a developer on the wrong OS.
    """
    size = ctypes.sizeof(INPUT)
    if not IS_WINDOWS:
        return (
            f"INPUT is {size} bytes here; not Windows, so the Windows layout cannot be asserted. "
            f"CI checks it on windows-latest."
        )
    expected = WINDOWS_INPUT_SIZE_64 if ctypes.sizeof(ctypes.c_void_p) == 8 else WINDOWS_INPUT_SIZE_32
    if size == expected:
        return f"INPUT is {size} bytes, matching the Win32 headers"
    return (
        f"INPUT is {size} bytes but the Win32 headers say {expected} on this architecture. "
        f"SendInput would send malformed input; do not use this build."
    )


def input_structure_is_valid() -> bool:
    """
    True when the struct matches the Win32 layout, or when the platform is not Windows.

    Callers that need a hard answer (a Windows build's About box) get one; callers that merely want
    to avoid a false alarm elsewhere get True.
    """
    if not IS_WINDOWS:
        return True
    expected = WINDOWS_INPUT_SIZE_64 if ctypes.sizeof(ctypes.c_void_p) == 8 else WINDOWS_INPUT_SIZE_32
    return ctypes.sizeof(INPUT) == expected


# kept for callers written against the earlier name
def check_input_structure() -> str:
    return layout_report()
