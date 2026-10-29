"""
The force-stop key.

Why this is not another RegisterHotKey, and why it is a low-level hook instead.

RegisterHotKey is what the toggle hotkey uses (see ui/hotkeys.py) and it is the right tool there. It is
the wrong tool for this, for a reason that only shows up when you use it: RegisterHotKey SWALLOWS the
key system-wide. Registering bare Enter that way would mean that while the autoclicker runs, Enter does
nothing in the browser, the editor, the game - anywhere. The program would break the user's keyboard.

So this uses WH_KEYBOARD_LL, which sees every key and decides what to do with it. That gives all three
things the user actually wants from a force stop:

  1. It stops on the FIRST press, immediately, with no modifier to hold.
  2. The decision is made in the hook itself and only sets a threading.Event, so it works even when the
     UI thread is busy or the window is unresponsive. A stop that goes through the interface is not a
     force stop.
  3. The key can be passed through, so Enter still reaches whatever has focus - or held back while a run
     is active, so an emergency stop cannot also submit a form or send a chat message.

Two details that are easy to get wrong and are handled here:

  - INJECTED EVENTS ARE IGNORED. The hook sees the autoclicker's own keystrokes. Without the injected
    check, a profile containing an Enter chord would stop itself the moment it ran.
  - THE HOOK CALLBACK MUST BE FAST. Windows silently removes a low-level hook whose callback takes too
    long ("LowLevelHooksTimeout"). The callback here does nothing but compare integers and set an Event;
    anything slower would be dropped by the OS and the key would appear to work only sometimes.

The hook exists only while a run is active: it is installed when the engine starts and removed when it
stops. A keyboard hook that is installed permanently is what a keylogger looks like, and there is no
reason to look like one while the program is idle.
"""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
from dataclasses import dataclass
from typing import Callable

IS_WINDOWS = sys.platform == "win32"

# --- Win32 constants ------------------------------------------------------------------------------
WH_KEYBOARD_LL = 13
HC_ACTION = 0

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

# KBDLLHOOKSTRUCT.flags
LLKHF_EXTENDED = 0x01
LLKHF_LOWER_IL_INJECTED = 0x02
LLKHF_INJECTED = 0x10

WM_APP = 0x8000
WM_QUIT = 0x0012

# Fixed-width types, for the same reason as in wininput.py: ctypes.wintypes.LONG is 4 bytes on Windows
# and 8 on 64-bit Linux, so a struct built from it changes shape with the platform it is measured on.
DWORD_ = ctypes.c_uint32
ULONG_PTR_ = ctypes.c_size_t


class KBDLLHOOKSTRUCT(ctypes.Structure):
    """
    The structure a WH_KEYBOARD_LL callback receives in lParam.

        typedef struct {
          DWORD     vkCode;
          DWORD     scanCode;
          DWORD     flags;
          DWORD     time;
          ULONG_PTR dwExtraInfo;
        } KBDLLHOOKSTRUCT;
    """

    _fields_ = [
        ("vkCode", DWORD_),
        ("scanCode", DWORD_),
        ("flags", DWORD_),
        ("time", DWORD_),
        ("dwExtraInfo", ULONG_PTR_),
    ]


# The offsets of the fields the decision uses, asserted in the tests on any platform.
HOOK_FIELD_OFFSETS = {"vkCode": 0, "scanCode": 4, "flags": 8, "time": 12}
EXPECTED_HOOK_PREFIX_BYTES = 16  # the four DWORDs before the pointer-sized field


# --- the decision, as a pure function --------------------------------------------------------------
@dataclass(frozen=True)
class KeyDecision:
    """What to do with one keyboard event."""

    stop: bool = False
    swallow: bool = False


def decide_key(
    *,
    vk: int,
    is_down: bool,
    injected: bool,
    target_vk: int,
    run_active: bool,
    swallow_while_running: bool,
) -> KeyDecision:
    """
    Decide what the hook should do with one event.

    Pure, and separate from the hook, so every case is testable without a keyboard or Windows - which
    matters because the interesting cases are the ones that are hard to reproduce by hand: an injected
    keystroke from the program itself, a release with no matching press, a press while idle.
    """
    # Nothing to force-stop if nothing is running.
    if not run_active:
        return KeyDecision()

    # The autoclicker's own keystrokes must never stop it. Without this a profile containing an Enter
    # chord would trip its own force stop on the first repetition.
    if injected:
        return KeyDecision()

    if vk != target_vk:
        return KeyDecision()

    if is_down:
        # The point of the feature: stop, and report the reason.
        return KeyDecision(stop=True, swallow=swallow_while_running)

    # A release. Do not stop again - one press, one stop - but hold the release back as well if the
    # press was held, so the focused application never sees a key-up without a key-down. Applications
    # generally ignore that, but some leave a modifier or a mode stuck.
    return KeyDecision(stop=False, swallow=swallow_while_running)


# --- the hook --------------------------------------------------------------------------------------
if IS_WINDOWS:
    HOOKPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,      # LRESULT
        ctypes.c_int,          # nCode
        ctypes.c_size_t,       # wParam
        ctypes.c_ssize_t,      # lParam
    )


class ForceStopWatcher:
    """
    Watches for one key on a dedicated thread and calls `on_trigger` when it is pressed.

    The thread exists because WH_KEYBOARD_LL callbacks are delivered to the thread that installed the
    hook, and that thread must be pumping messages. Tk owns the main thread's loop, so this gets its own.

    `on_trigger` runs on that thread and must be trivial - it is expected to set a threading.Event. It
    must not touch Tk.
    """

    def __init__(
        self,
        on_trigger: Callable[[], None],
        *,
        target_vk: int,
        swallow_while_running: bool,
        run_active: Callable[[], bool],
        time_fn: Callable[[], int] | None = None,
    ) -> None:
        self._on_trigger = on_trigger
        self._target_vk = target_vk
        self._swallow = swallow_while_running
        self._run_active = run_active
        self._time_fn = time_fn or (lambda: 0)

        self._commands: queue.Queue[tuple[str, object]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._hook = None
        # A CFUNCTYPE object that is garbage collected while Windows still holds the pointer crashes the
        # process on the next keystroke. Keeping the reference here is load-bearing, not tidiness.
        self._proc = None
        self._result: queue.Queue[tuple[bool, str]] = queue.Queue()

        self.available = IS_WINDOWS
        self.error = ""
        self.installed = False
        self.triggers = 0  # counted for the self test and for the status line

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> bool:
        """Begin the watcher thread. Installs nothing yet: the hook is armed per run."""
        if not self.available:
            self.error = "the force stop key needs Windows (WH_KEYBOARD_LL)"
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        self._ready.clear()
        self._thread = threading.Thread(target=self._pump, name="autoclick-forcestop", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            self.error = "the force stop thread did not start"
            return False
        return True

    def arm(self) -> bool:
        """Install the hook. Call when a run starts. Returns False (with `error`) on failure."""
        return self._command("install")

    def disarm(self) -> bool:
        """Remove the hook. Call when a run ends, so no keyboard hook exists while idle."""
        return self._command("uninstall")

    def close(self) -> None:
        if self._thread is None:
            return
        try:
            self._command("quit")
            self._thread.join(timeout=2.0)
        except Exception:  # noqa: BLE001
            pass
        self._thread = None

    def _command(self, name: str) -> bool:
        if not self.available or self._thread is None or not self._thread.is_alive():
            self.error = self.error or "the force stop watcher is not running"
            return False
        while not self._result.empty():
            try:
                self._result.get_nowait()
            except queue.Empty:
                break
        self._commands.put((name, None))
        # wake the pump: it is blocked in GetMessageW
        try:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_APP, 0, 0)
        except Exception:  # noqa: BLE001
            pass
        try:
            ok, msg = self._result.get(timeout=3.0)
        except queue.Empty:
            self.error = f"no answer to {name!r} from the force stop thread"
            return False
        if not ok:
            self.error = msg
        return ok

    # ------------------------------------------------------------------ the pump thread

    def _pump(self) -> None:
        import ctypes.wintypes as wt

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self._bind(user32)
        self._thread_id = kernel32.GetCurrentThreadId()

        # Force the message queue into existence before anyone tries to post to it; a PostThreadMessage
        # to a thread with no queue is dropped, which would leave arm() waiting for an answer forever.
        msg = wt.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, WM_APP, WM_APP, 0)

        self._ready.set()

        try:
            while True:
                got = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if got <= 0:
                    break
                self._drain_commands(user32)
                if self._closing:
                    break
        finally:
            self._uninstall(user32)
            self.installed = False

    @property
    def _closing(self) -> bool:
        return getattr(self, "_close_flag", False)

    def _drain_commands(self, user32) -> None:
        while True:
            try:
                name, _ = self._commands.get_nowait()
            except queue.Empty:
                return
            if name == "install":
                ok, err = self._install(user32)
                self._result.put((ok, err))
            elif name == "uninstall":
                self._uninstall(user32)
                self._result.put((True, ""))
            elif name == "quit":
                self._close_flag = True
                self._uninstall(user32)
                self._result.put((True, ""))
                user32.PostQuitMessage(0)
                return

    # ------------------------------------------------------------------ install / remove

    def _bind(self, user32) -> None:
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = (
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, DWORD_,
        )
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.CallNextHookEx.argtypes = (
            ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t,
        )
        user32.UnhookWindowsHookEx.restype = ctypes.c_bool
        user32.UnhookWindowsHookEx.argtypes = (ctypes.c_void_p,)
        self._user32 = user32

    def _install(self, user32) -> tuple[bool, str]:
        if self._hook:
            return True, ""
        # A plain function rather than a bound method: ctypes needs a stable C-callable, and a bound
        # method's lifetime is not under our control.
        proc = HOOKPROC(self._hook_proc_impl)

        handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, None, 0)
        if not handle:
            code = ctypes.get_last_error()
            self._proc = None
            return False, f"SetWindowsHookEx failed (Win32 error {code})"

        self._proc = proc      # must outlive the hook
        self._hook = handle
        self.installed = True
        self.error = ""
        return True, ""

    def _uninstall(self, user32) -> None:
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
        self._proc = None
        self.installed = False

    # ------------------------------------------------------------------ the callback

    def _hook_proc_impl(self, n_code, w_param, l_param):
        """
        Runs for EVERY keystroke while the hook is installed. Must return in microseconds.

        Anything slow here and Windows drops the hook: the documentation warns that a callback exceeding
        LowLevelHooksTimeout is silently removed, which would look like the key working only sometimes.
        So: no allocation, no logging, no Tk. Compare integers, optionally set an Event, return.
        """
        try:
            if n_code != HC_ACTION:
                return self._user32.CallNextHookEx(None, n_code, w_param, l_param)

            is_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
            is_up = w_param in (WM_KEYUP, WM_SYSKEYUP)
            if not (is_down or is_up):
                return self._user32.CallNextHookEx(None, n_code, w_param, l_param)

            info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            injected = bool(info.flags & (LLKHF_INJECTED | LLKHF_LOWER_IL_INJECTED))

            decision = decide_key(
                vk=int(info.vkCode),
                is_down=is_down,
                injected=injected,
                target_vk=self._target_vk,
                run_active=bool(self._run_active()),
                swallow_while_running=self._swallow,
            )

            if decision.stop:
                self.triggers += 1
                self._on_trigger()

            if decision.swallow:
                return 1  # consumed: do not pass it on
            return self._user32.CallNextHookEx(None, n_code, w_param, l_param)
        except Exception:
            # Never break the user's keyboard because of a bug here. Passing the key through is always
            # the safe answer.
            try:
                return self._user32.CallNextHookEx(None, n_code, w_param, l_param)
            except Exception:
                return 0


def make_watcher(
    on_trigger: Callable[[], None],
    *,
    key_name: str,
    swallow_while_running: bool,
    run_active: Callable[[], bool],
) -> ForceStopWatcher:
    """
    Build a watcher for a named key.

    Resolving the name here rather than in the caller means an unusable name is reported once, at setup,
    instead of silently registering the wrong key.
    """
    from .wininput import key_to_vk

    return ForceStopWatcher(
        on_trigger,
        target_vk=key_to_vk(key_name),
        swallow_while_running=swallow_while_running,
        run_active=run_active,
    )
