"""
Entry point.

The import is written as `from autoclick.ui.app import main`, NOT relative, and the reason is a bug
found by actually running the frozen executable rather than assuming:

    ImportError: attempted relative import with no known parent package

PyInstaller runs this file as the top-level script named `__main__`, so the package context a
relative import needs does not exist. The absolute form works both frozen and from source, because
`src` is on the path either way.

`--selftest` exists for the same reason: a build that produces an executable is not the same as a
build that produces an executable that can draw a window. It constructs the whole UI, renders it
once, reports what it found and exits. CI runs it against the packaged binary, which is the only way
to catch a missing tkinter or a broken Tk data directory before a user does.
"""

from __future__ import annotations

import sys


def _setup_dpi() -> None:
    """
    Windows DPI awareness must be set BEFORE any window exists.

    Otherwise a coordinate captured from the cursor and a coordinate sent to SendInput are in
    different spaces on a scaled display, and fixed-position clicks land in the wrong place - a bug
    that only appears on high-DPI screens, which is most modern laptops.
    """
    if sys.platform != "win32":
        return
    import ctypes

    try:
        # per-monitor v2: correct on mixed-DPI multi-monitor setups
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass  # older Windows: still works, coordinates just less precise


def selftest() -> int:
    """
    Build the entire interface, render it once, and report. Exit 0 on success.

    Deliberately does NOT call mainloop: an unattended run must terminate. `update()` performs a real
    render pass, so a Tk that cannot create widgets or load its fonts fails here rather than in front
    of a user.
    """
    import tkinter as tk

    from autoclick import __version__
    from autoclick.core.wininput import IS_WINDOWS, layout_report
    from autoclick.ui.app import App
    from autoclick.ui import store

    print(f"autoclick {__version__}")
    print(f"python   {sys.version.split()[0]}")
    print(f"platform {sys.platform}")
    print(f"frozen   {bool(getattr(sys, 'frozen', False))}")
    print(f"storage  {store.storage_note()}")
    print(f"input    {layout_report()}")

    root = tk.Tk()
    root.withdraw()  # do not flash a window during a test run
    try:
        app = App(root)
        root.update_idletasks()
        root.update()

        # count what was actually built, so an interface that silently failed to populate is visible
        def count(widget) -> int:
            n = 1
            for child in widget.winfo_children():
                n += count(child)
            return n

        widgets = count(root)
        notebooks = len([w for w in _walk(root) if w.winfo_class() == "TNotebook"])
        entries = len([w for w in _walk(root) if w.winfo_class() == "TEntry"])
        frames = len([w for w in _walk(root) if w.winfo_class() == "TFrame"])

        print(f"widgets  {widgets} total, {frames} frames, {entries} entries, {notebooks} notebook")
        print(f"tabs     {len(app.nb.tabs())}")
        print(f"hotkey   {app.current.hotkey} (registered: {app.hotkey.registered})")

        # the interface must have real content, not an empty shell
        problems = []
        if widgets < 40:
            problems.append(f"only {widgets} widgets were created")
        if len(app.nb.tabs()) != 3:
            problems.append(f"expected 3 tabs, found {len(app.nb.tabs())}")
        if entries < 8:
            problems.append(f"only {entries} entry fields; the simple tab should have most of them")

        # the engine must be able to drive a profile with the recording backend
        from autoclick.core.engine import Engine
        from autoclick.core.model import Profile
        from autoclick.core.wininput import NullBackend

        backend = NullBackend()
        engine = Engine(backend)
        stats = engine.run_blocking(Profile(interval_ms=1, repeat=5, at_once=2))
        print(f"engine   {stats.clicks_sent} clicks from 5 repeats x2 at once")
        if stats.clicks_sent != 10:
            problems.append(f"engine sent {stats.clicks_sent} clicks, expected 10")

        print(f"window   {root.winfo_width()}x{root.winfo_height()} (withdrawn, so may be 1x1)")

        if problems:
            for p in problems:
                print(f"FAIL: {p}")
            return 2
        print("SELFTEST OK")
        return 0
    finally:
        root.destroy()


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def main() -> int:
    _setup_dpi()

    if "--selftest" in sys.argv:
        return selftest()
    if "--version" in sys.argv:
        from autoclick import __version__

        print(__version__)
        return 0

    from autoclick.ui.app import main as ui_main

    return ui_main()


if __name__ == "__main__":
    raise SystemExit(main())
