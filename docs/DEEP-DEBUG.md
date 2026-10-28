# Deep debug pass — what was wrong, and how each fix was proven

Date: 2026-10-28. Scope: the whole program — the engine, the interface, storage, error contracts.

Method: read every module, then write tests that FAIL if a reading-based suspicion is correct. A test
that passes means the suspicion was wrong, which is equally worth knowing. Two of the sixteen
suspicions turned out to be my own mistakes and are recorded here as such.

**Result: 6 real bugs, 2 of them severe enough that the program was not really usable.**

---

## 1. A stopped key chord left keys held down — critical

**Found by:** reading `_fire_chord` and noticing the early `return` inside the press loop.

**Reproduced:**
```
steps: KeyStep(keys=["ctrl", "shift", "t"], gap_ms=50), stop arrives during the chord
result: pressed-and-never-released: ['ctrl']
```

**Why it matters:** the user's keyboard stays stuck until they press ctrl physically. Of every failure
this program could have, this is the worst.

**Fixed:** the release loop moved into a `finally`, so it runs whatever happens. It releases every key
that actually went down, in reverse order, and keeps going if one release raises (recording the error
instead, because a stuck modifier outranks a tidy error report). When the run was halted, release is
immediate rather than paced by the gap.

## 2. The app was usable only once per launch — critical, two independent causes

**Found by:** writing the first UI test, which asserted Start returns to enabled after a run. It
failed, and instrumenting the path explained why.

```
progress callbacks delivered: 0
engine clicks/stat    : 4 4
shown clicks label    : 0
start button state    : disabled
```

**Cause A — Tk called from the wrong thread.** The engine runs on its own thread and reports progress.
The UI turned that into `self.root.after(0, self._refresh_status, s)`. `after` is a Tcl call, and Tcl
is bound to the thread that created it, so calling it from the engine thread **fails silently** — no
exception, no callback, ever. The interface therefore never learned a run had started, progressed or
ended.

**Cause B — a finishing condition that could never be met.** `_refresh_status` restored the buttons
only when `not engine.is_running()`. The last progress report is sent from inside the engine loop
while that thread is alive, so `is_running()` was True and `_after_run()` was declined. No further
callback was ever coming. Start stayed greyed out after one perfect run.

**Fixed:**
- A `queue.Queue` is the thread-safe hand-off; the UI drains it from its own thread.
- The end-of-run transition moved to a polling loop the UI drives itself. It decides from state it can
  always observe (the thread is dead **and** at least one report arrived) rather than from a message
  arriving at the right moment.
- A subtlety found while fixing it: the first version called `_drain_queue()` before `start()`, found
  no engine running, and returned without scheduling anything — so nothing polled at all. The second
  declared the run finished on the first tick, because `is_running()` is False for a moment after the
  thread is spawned, and showed the pre-run zeroes. Both are why the guard is "dead **and** reported".

## 3. `max_duration_ms` was not a ceiling

**Found by:** reading the loop and noticing the check sits before the tick, never inside one.

**Reproduced:**
```
max_duration_ms=1000 with a 5000 ms WaitStep inside  -> ran 5000 ms
max_duration_ms=500  with six 200 ms key gaps        -> ran 2400 ms
```

**Why it matters:** it is presented as the safety net for "I started it and walked away".

**Fixed:** it is now an absolute deadline, enforced inside every sleep as well as between repetitions.

## 4. A `WaitStep` could not be interrupted

**Found by:** the same reading pass. The step called `self._sleep_fn(step.ms)` directly — one lump, so
Stop did nothing for the whole wait and the time limit could not cut it short.

**Reproduced:** a 30-second wait with a stop after the second sleep call: `stopped_by` stayed
`"finished"` instead of `"user pressed stop"`.

**Fixed:** routed through the same interruptible sleep as everything else.

## 5. Lateness and missed-tick counters measured the wrong deadline

**Found by:** reading the accounting block, which compared against `start_ms + index * interval` —
the deadline of the tick that had *just fired* — with a 250 ms tolerance.

**Two consequences:**
- A repetition that overran its slot was never counted.
- `BackToBack` (interval 0) computed a deadline of `start + 0`, so every tick of a perfectly healthy
  "as fast as possible" run recorded `elapsed` ms of lateness and grew `missed_ticks` without bound.

**Fixed:** measured against the slot the repetition actually had to fit in, and skipped entirely when
there is no interval — there is nothing to be late for.

## 6. `parse_hotkey` broke its own error contract

**Found by:** a test for an unknown key name, which raised `InputError` (a `RuntimeError`) where the
docstring promises `ValueError`. A caller catching the documented type missed it.

**Fixed:** the parser translates, keeping its contract.

---

## Not bugs, but wrong on arrival

- **A dead guard that looked like a safety check:** `hasattr(ctypes, "wintypes")` is always False,
  because `wintypes` is a submodule that `ctypes` does not import for you. Harmless only because the
  next line reassigned the value. Removed.
- **A document that described a screen that did not exist:** the installed-build notice says "the
  location is stated in the About panel", and the README promised the same. There was no About panel.
  It now exists and states the storage path, what is verified, and what cannot be verified here.
- **32 translations no widget displayed.** Removed, so a translator is not asked to maintain text that
  never appears.
- **The language switch asked for a restart.** A language is a preference, not a structural change.
  Labels are now registered as they are built and re-pointed in place.

---

## Two suspicions that were my own mistakes

Recorded because a debug log that only lists wins is not a debug log.

**"A 400 ms click in a 500 ms slot drifts."** It does not. The wait after each click is recomputed
from elapsed time, so it waits 100 ms instead of 500 and the next click lands exactly on its deadline.
I wrote the test expecting lateness; the engine was right. The test now asserts the correct behaviour,
and the overrun case (a 400 ms click in a 100 ms slot) is asserted separately.

**"Stop mid-chord does not release."** It did not, but my first test said so for the wrong reason: it
compared one backend's `key_down` events against a *different* backend's `key_up` events, and reported
"pressed [] but released [a]". The real bug was found by the other test in that class, which used a
single recorder.

---

## Verification

```
179 tests pass, 6 skipped (Windows-only)
  20 UI tests drive real Tk widgets under Xvfb
  27 storage and hotkey tests: atomic writes, corruption tolerance, error contracts
  14 engine tests written specifically for this pass
```

Both PyInstaller builds were rebuilt and run their own `--selftest`:

```
115 widgets, 4 tabs, 12 bound labels all resolvable in en and fa
engine: 10 clicks from 5 repeats x 2 at once
SELFTEST OK
```

The selftest caught the tab count itself when the About panel was added — which is the point of having
it.

`.github/workflows/build.yml` now also fails if the UI tests were skipped on Windows, and runs
`scripts/check_i18n.py`, so a missing translation cannot reach a release.

---

## Left alone deliberately

- **`BackToBack` has no floor.** A 0 ms interval will use a whole CPU core doing nothing but waiting
  between clicks. That is what "as fast as possible" means, and the achieved rate is reported rather
  than an interval that was never held.
- **The default hotkey is F6.** Registering it can fail if another program owns it; that is reported
  next to the field and is not fatal, because the buttons still work.
- **No process targeting.** Input goes to whatever has focus. Targeting another process's window is
  what turns a tool into something antivirus software should flag.
