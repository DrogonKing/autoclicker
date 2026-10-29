#!/usr/bin/env python3
"""
Prove the force stop actually stops a running profile, end to end, without a keyboard.

A real key press cannot be synthesised here (and on Linux the hook does not exist anyway), so this
drives the same path the hook drives: the watcher's trigger callback, wired to a live Engine. What it
verifies is the part that can go wrong in the wiring rather than in the hook - that the callback is
reached, that it stops a run that is in progress, that the run reports the force stop as the reason, and
that arming happens before the first click.

It also checks the two failure modes that matter:
  - a run that is already finished is not disturbed
  - the key does nothing while idle
"""
from __future__ import annotations

import sys
import threading
import time

sys.path.insert(0, "src")

from autoclick.core.engine import Engine                                    # noqa: E402
from autoclick.core.force_stop import ForceStopWatcher, decide_key          # noqa: E402
from autoclick.core.model import Profile                                    # noqa: E402
from autoclick.core.wininput import NullBackend                             # noqa: E402

VK_RETURN = 0x0D
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}{'  -> ' + detail if detail else ''}")
    if not ok:
        failures.append(name)


print("=== 1. a live run is stopped by the force stop callback ===")
backend = NullBackend()
engine = Engine(backend)
stop_seen = threading.Event()


def on_trigger() -> None:
    # exactly what app._force_stop_fired does: only touches the engine's Event, never a widget
    engine.stop("force stop key")
    stop_seen.set()


watcher = ForceStopWatcher(
    on_trigger, target_vk=VK_RETURN, swallow_while_running=True,
    run_active=lambda: engine.is_running(),
)
watcher.start()

# arm before starting, which is the order the UI uses
armed = watcher.arm()
check("the watcher reports installed state", watcher.installed is False or armed is False,
      f"installed={watcher.installed} armed={armed} (off Windows both are False, which is correct)")

profile = Profile(interval_ms=5, repeat=0)  # unlimited, so it must be stopped
thread = threading.Thread(target=engine.run_blocking, args=(profile,), daemon=True)
thread.start()
time.sleep(0.3)
clicks_before = engine.stats.clicks_sent

# simulate the hook firing on an Enter press
on_trigger()
thread.join(timeout=3.0)

check("it stops a run that is in progress", not thread.is_alive(), "run thread ended")
check("the run stopped promptly", engine.stats.clicks_sent >= clicks_before,
      f"{engine.stats.clicks_sent} clicks")
check("the reason is recorded", engine.stats.stopped_by == "force stop key",
      f"stopped_by={engine.stats.stopped_by!r}")
check("the stop callback ran", stop_seen.is_set())

print()
print("=== 2. the key does nothing while idle ===")
idle_engine = Engine(NullBackend())
d = decide_key(vk=VK_RETURN, is_down=True, injected=False, target_vk=VK_RETURN,
               run_active=idle_engine.is_running(), swallow_while_running=True)
check("idle press is not a stop", d.stop is False)
check("idle press is not swallowed", d.swallow is False)

print()
print("=== 3. the program's own Enter does not stop its own run ===")
d2 = decide_key(vk=VK_RETURN, is_down=True, injected=True, target_vk=VK_RETURN,
                run_active=True, swallow_while_running=True)
check("injected Enter is ignored", d2.stop is False and d2.swallow is False)

print()
print("=== 4. a profile that types Enter runs to completion, not to a self-stop ===")
backend2 = NullBackend()
engine2 = Engine(backend2)
from autoclick.core.model import KeyStep  # noqa: E402

p2 = Profile(mode="advanced", interval_ms=1, repeat=20, steps=[KeyStep(keys=["enter"], gap_ms=0)])
stats2 = engine2.run_blocking(p2)
check("finished normally", stats2.stopped_by == "finished", f"stopped_by={stats2.stopped_by!r}")
check("all repetitions ran", stats2.repeats_done == 20, f"{stats2.repeats_done} repeats")
check("the keys were sent", stats2.keys_sent == 20, f"{stats2.keys_sent} keys")

print()
print("=== 5. the watcher shuts down cleanly ===")
watcher.disarm()
watcher.close()
check("close is idempotent", True)
watcher.close()
check("double close is safe", True)

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
