# AutoClicker

A customizable autoclicker for Windows. Portable and installed builds.

## What it does

- **Interval between clicks**, in milliseconds. `0` means as fast as the machine can manage.
- **Repeat count.** An exact number, or `0` for unlimited.
- **Scheduled start.** Type `11:50:20` and it begins at that time. If that time has already passed
  today it waits for tomorrow's, rather than firing immediately.
- **Several clicks at the same instant**, with no gap between them - up to 100.
- **Key chords with a millisecond gap between the keys**, which is what makes `ctrl+shift+t` arrive
  as three distinguishable presses instead of an instantaneous blur that many applications ignore.
- **Sequences (advanced tab).** Any mix of clicks, key chords and waits, in order.
- **Hotkey to start and stop** (`F6` by default) that works while the app is unfocused.
- **Test mode**: runs the real timing engine against a recorder instead of your mouse, so a profile
  can be checked before it clicks anything.
- English and Persian interface.

## Install

Two builds, both 64-bit Windows:

| | |
|---|---|
| `AutoClicker-1.0.0-setup.exe` | installer; per-user so there is no administrator prompt |
| `AutoClicker-portable.zip` | unpack anywhere and run `AutoClicker.exe` |

**Neither is code-signed.** SmartScreen will warn you the first time: `More info` → `Run anyway`.
The notice inside the download explains exactly what the program touches, and the source is here to
read.

Where settings live:
- installed → `%APPDATA%\AutoClicker`
- portable → a `profiles` folder beside the executable

## The part that is usually wrong

Most autoclickers sleep between clicks:

```python
while running:
    click()
    sleep(interval)
```

Each iteration costs the sleep **plus** however long the click took. A 100 ms interval on a machine
where clicking costs 3 ms actually fires every 103 ms, so after a thousand clicks you are three
seconds late, and an hour in the last click is minutes from where it was asked to be.

This one computes absolute deadlines: tick *N* is due at `start + N × interval`, whatever any
individual click cost. When the machine genuinely cannot keep up, the tick is reported as late rather
than firing a burst to catch up - a machine-gun burst is the last thing a user wants from a program
they set running.

Tested, not asserted:

```
test_total_time_is_independent_of_per_click_cost
    simulates a 7 ms click cost and checks the 200th click is still at 200 × interval
```

## Tests

```
94 tests run anywhere, 9 more run on Windows only
```

The Windows-only ones are the reason CI runs on `windows-latest`: the `SendInput` structure layout
and the virtual-key table cannot be verified on the machine this was written on (they are 40 bytes on
Windows and 56 on Linux, because `ULONG` differs). A wrong layout does not raise an error - it sends
malformed input, so CI checks it before a release rather than a user reporting it.

The workflow **fails if those tests are skipped**, so a green build means they actually ran.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
pytest
```

## Layout

```
src/autoclick/
  core/          no tkinter, no Windows dependency except wininput (guarded)
    model.py       profiles, steps, validation
    timing.py      deadlines, drift, clock arithmetic
    schedule.py    fixed-interval and back-to-back, duration parsing
    engine.py      the loop; clock and sleep are injected
    wininput.py    SendInput; NullBackend for tests and dry runs
  ui/
    app.py         the window
    strings.py     EN + FA
    store.py       profile storage, atomic writes
    hotkeys.py     RegisterHotKey on its own thread
```

The core having no UI dependency is not tidiness for its own sake: it is what allows the timing to be
tested properly. `Engine` takes `time_fn` and `sleep_fn`, so a test runs 10,000 clicks in
milliseconds and asserts exactly where each one landed. An engine that sleeps on the real clock can
only be tested by waiting, which means it is not really tested.

## Deliberate limits

- Windows only. `SendInput` has no portable equivalent, and a build that cannot send input is not
  this program.
- No process targeting. It sends input to whatever has focus, because the alternative - hooking
  another process's window - is what turns a tool into something antivirus software should flag.
- Not code-signed. Signing needs a certificate; the unsigned notice states the behaviour plainly
  instead of leaving the warning unexplained.
