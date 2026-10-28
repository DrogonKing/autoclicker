"""
A global hotkey.

Why this is hand-rolled rather than a library: an autoclicker must be startable and, more importantly,
STOPPABLE without the app being focused. If Stop needs a mouse click on the window, a profile that
clicks the same spot as the Stop button makes the program unstoppable by mouse. The hotkey is the
safety release, so it must not depend on a package that may fail to install.

On Windows: RegisterHotKey on a dedicated thread with its own message loop. Tk runs its own loop on
the main thread and cannot service a second one.

Off Windows: a no-op that reports itself unavailable, so the app still runs for development and the
tests can import it.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from typing import Callable

IS_WINDOWS = sys.platform == "win32"

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT}


def parse_hotkey(spec: str) -> tuple[int, int]:
    """
    "ctrl+shift+f6" -> (modifier mask, virtual key).

    Raises ValueError with a readable message rather than registering the wrong key, because a
    hotkey that silently does not work is discovered at the worst moment.
    """
    from ..core.wininput import InputError, key_to_vk

    parts = [p.strip().lower() for p in (spec or "").split("+") if p.strip()]
    if not parts:
        raise ValueError("hotkey is empty")
    mods = 0
    key_part = None
    for p in parts:
        if p in MODIFIERS:
            mods |= MODIFIERS[p]
        else:
            if key_part is not None:
                raise ValueError(f"only one non-modifier key is allowed, got {key_part!r} and {p!r}")
            key_part = p
    if key_part is None:
        raise ValueError("hotkey needs a key, e.g. ctrl+shift+f6 or f8")
    try:
        vk = key_to_vk(key_part)
    except InputError as e:
        # key_to_vk raises InputError (a RuntimeError). This function's contract is ValueError, and a
        # caller that catches ValueError - which is what the docstring promises - would have missed it.
        raise ValueError(str(e)) from None
    return mods, vk


class Hotkey:
    """
    Registers one global hotkey and calls `callback` on press.

    The callback runs on the hotkey thread. It must not touch Tk directly; the app marshals it onto
    the UI thread with `after`, which is what `on_press` wrapping does in app.py.
    """

    def __init__(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._registered = False
        self.error = ""
        self.available = IS_WINDOWS

    def register(self, spec: str) -> bool:
        """
        Register the hotkey, replacing any previous one.

        Returns False (with `error` set) when the combination is taken by another program. That is a
        normal outcome and the UI reports it; it is not an exception, because the app is perfectly
        usable with the button alone.
        """
        self.unregister()
        if not self.available:
            self.error = "global hotkeys are only available on Windows"
            return False
        try:
            mods, vk = parse_hotkey(spec)
        except ValueError as e:
            self.error = str(e)
            return False

        self._mods, self._vk = mods | MOD_NOREPEAT, vk
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._pump, name="autoclick-hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)
        return self._registered

    def _pump(self) -> None:
        """Own this thread's message queue and pump it. RegisterHotKey requires a queue on the
        calling thread, which is why registering happens here and not on the main thread."""
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._thread_id = kernel32.GetCurrentThreadId()

        ok = user32.RegisterHotKey(None, 1, self._mods, self._vk)
        self._registered = bool(ok)
        if not ok:
            code = ctypes.get_last_error()
            # 1409 is ERROR_HOTKEY_ALREADY_REGISTERED
            self.error = (
                "that hotkey is already used by another program"
                if code == 1409
                else f"RegisterHotKey failed (Win32 error {code})"
            )
        self._ready.set()
        if not ok:
            return

        # `ctypes.wintypes` is a submodule and is NOT an attribute of `ctypes` unless it has been
        # imported, so a `hasattr(ctypes, "wintypes")` check is always False - it looks like a guard and
        # is not one. Imported explicitly here (the third import in this module, kept because this
        # function is the only place MSG is needed).
        import ctypes.wintypes as wt

        msg = wt.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        self._callback()
                    except Exception:
                        # a callback failure must not kill the hotkey thread, or the user loses the
                        # only way to stop the program
                        pass
        finally:
            user32.UnregisterHotKey(None, 1)

    def unregister(self) -> None:
        if not self.available or self._thread is None:
            self._registered = False
            return
        if self._thread_id:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.UnregisterHotKey(None, 1)
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        self._thread_id = None
        self._registered = False

    @property
    def registered(self) -> bool:
        return self._registered
