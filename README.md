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
- **Force stop on a bare key** (`Escape` by default): one press, no modifier, stops a run instantly. It
  is read inside a keyboard hook rather than through the interface, so it still works if the window is
  not responding.
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

## The force stop key

One key, no modifier, and it stops immediately. Three details worth knowing, because each of them is a
choice rather than an implementation accident:

**Why Escape.** Both `Escape` and `Enter` are single keys needing no modifier, so either works
mechanically. `Escape` is the better choice because it already carries a "stop" meaning in games and
full-screen applications, and because `Enter` is a key you press constantly - submitting forms, sending
messages. Binding the panic button to an everyday key means pressing it accidentally does something
drastic, and pressing it deliberately is indistinguishable from normal use.

**Why not a normal hotkey.** `RegisterHotKey` - what the F6 toggle uses - *swallows the key
system-wide*. Registering a bare key that way would mean that while the autoclicker is open, that key
does nothing in your browser, editor or game. The program would break your keyboard. So the force stop
uses a low-level keyboard hook instead, which sees the key and decides what to do with it.

**It works when the window does not.** The stop is decided inside the hook and only sets a
`threading.Event`. Routing it through the interface would mean waiting for the event loop, and a stop
that depends on the interface being responsive is not a force stop.

**Your own keypresses do not stop your own run.** The hook ignores injected keystrokes, so a profile
that types `Escape` - closing a dialog as part of its sequence, say - runs to completion instead of
tripping its own emergency stop. Verified for both: an `Escape` profile ran `15 repeats` and an `Enter`
profile `20 repeats`, both `stopped_by='finished'`.

**What happens to the key itself.** By default it is held back while a run is active, so the panic
button cannot also close a window or cancel something in whatever has focus. Turn that off and the key
is passed through untouched. When nothing is running the key is completely normal either way - the hook
is only installed for the duration of a run.

The key is configurable, and the setting travels with the profile.

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
217 tests run anywhere, 6 more run on Windows only
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
