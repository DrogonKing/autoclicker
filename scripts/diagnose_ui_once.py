#!/usr/bin/env python3
"""
Diagnose why the app is usable only once per launch.

Symptoms: after a completed run the Start button stays disabled and the stats read 0.

The handoff is: the engine reports progress from its own thread -> the UI marshals it onto the Tk
thread with `after(0, ...)` -> `_refresh_status` notices the engine has stopped and calls
`_after_run` to restore the buttons. So the whole transition depends on a progress callback that
arrives AFTER the engine thread has died. The last callback is sent from inside the loop while the
thread is still alive, so `is_running()` is still True and `_after_run` is not called; no further
callback ever comes, and the buttons stay as they were.
"""
import subprocess
import sys
import textwrap

PROBE = textwrap.dedent('''
    import sys, time, tkinter as tk
    sys.path.insert(0, "src")
    from autoclick.ui.app import App

    root = tk.Tk(); root.withdraw()
    app = App(root)
    app.v_interval.set("1"); app.v_count.set("4")

    calls = []
    real = app._refresh_status
    def traced(stats=None):
        calls.append({
            "engine": app.engine is not None,
            "running": app.engine.is_running() if app.engine else None,
            "repeats": app.engine.stats.repeats_done if app.engine else None,
            "clicks": app.engine.stats.clicks_sent if app.engine else None,
            "start_state": str(app.start_btn["state"]),
        })
        return real(stats)
    app._refresh_status = traced

    app._start(dry=True)
    end = time.monotonic() + 3.0
    while time.monotonic() < end:
        root.update(); time.sleep(0.01)

    print("progress callbacks delivered:", len(calls))
    for c in calls[-6:]:
        print("  ", c)
    print()
    print("engine running at end :", app.engine.is_running())
    print("engine clicks/stat    :", app.engine.stats.clicks_sent, app.engine.stats.repeats_done)
    print("shown clicks label    :", app.stat_labels["s.clicks"]["text"])
    print("start button state    :", str(app.start_btn["state"]))
    print("stop button state     :", str(app.stop_btn["state"]))
    print()
    print("VERDICT:", "USABLE ONLY ONCE (Start left disabled)" if str(app.start_btn["state"]) == "disabled" else "ok")
''')

with open("/tmp/ui_probe.py", "w") as f:
    f.write(PROBE)

r = subprocess.run(
    ["xvfb-run", "-a", "--server-args=-screen 0 1200x900x24", ".venv/bin/python", "/tmp/ui_probe.py"],
    cwd="/root/autoclicker", capture_output=True, text=True, timeout=300,
)
print(r.stdout[-2500:] or r.stderr[-2500:])
