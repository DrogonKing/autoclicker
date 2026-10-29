"""
The task model.

Everything here is pure data: no I/O, no platform calls, no clock. That is deliberate. The parts of
an autoclicker that actually go wrong are arithmetic (drift, missed deadlines, wrong count), and
arithmetic can only be tested if it is separated from the machinery that fires the clicks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .errors import ParseError, ProfileError

MouseButton = Literal["left", "right", "middle"]
PositionMode = Literal["cursor", "fixed"]

# Bounds. A UI will offer these as limits; the model enforces them so a hand-edited profile file
# cannot ask for a 40-day wait or a negative interval.
MIN_INTERVAL_MS = 0
MAX_INTERVAL_MS = 24 * 60 * 60 * 1000
MIN_REPEAT = 1
MAX_REPEAT = 10_000_000
MAX_AT_ONCE = 100
MAX_STEPS = 500
MAX_GAP_MS = 60_000


@dataclass
class ClickStep:
    """One click, or `at_once` simultaneous clicks at the same instant."""

    button: MouseButton = "left"
    position: PositionMode = "cursor"
    x: int = 0
    y: int = 0
    # "چندتا کلیک همزمان": several clicks fired in the same instant, with no gap between them.
    at_once: int = 1
    double: bool = False
    kind: str = field(default="click", init=False)

    def validate(self) -> None:
        if self.button not in ("left", "right", "middle"):
            raise ProfileError(f"unknown mouse button: {self.button!r}")
        if self.position not in ("cursor", "fixed"):
            raise ProfileError(f"unknown position mode: {self.position!r}")
        if not (1 <= self.at_once <= MAX_AT_ONCE):
            raise ProfileError(f"clicks at once must be 1..{MAX_AT_ONCE}, got {self.at_once}")
        if self.position == "fixed" and not _in_screen_range(self.x, self.y):
            raise ProfileError(f"fixed position ({self.x}, {self.y}) is outside any screen")


@dataclass
class KeyStep:
    """
    A chord plus the gap between its keys.

    "چندتا کلید با فاصله زمانی چند میلی ثانیه": the gap is what makes ctrl+alt+t behave like three
    distinguishable presses rather than an instantaneous, often-ignored blur.
    """

    keys: list[str] = field(default_factory=lambda: ["space"])
    # ms between the keys going down, and between them coming up
    gap_ms: int = 30
    hold_ms: int = 0
    kind: str = field(default="key", init=False)

    def validate(self) -> None:
        if not self.keys:
            raise ProfileError("a key step needs at least one key")
        if len(self.keys) > 8:
            raise ProfileError("a chord of more than 8 keys is almost certainly a mistake")
        for k in self.keys:
            if not isinstance(k, str) or not k.strip():
                raise ProfileError("key names cannot be empty")
        if not (0 <= self.gap_ms <= MAX_GAP_MS):
            raise ProfileError(f"key gap must be 0..{MAX_GAP_MS} ms, got {self.gap_ms}")
        if not (0 <= self.hold_ms <= MAX_GAP_MS):
            raise ProfileError(f"hold must be 0..{MAX_GAP_MS} ms, got {self.hold_ms}")


@dataclass
class WaitStep:
    """An explicit pause inside the sequence."""

    ms: int = 100
    kind: str = field(default="wait", init=False)

    def validate(self) -> None:
        if not (0 <= self.ms <= MAX_GAP_MS):
            raise ProfileError(f"wait must be 0..{MAX_GAP_MS} ms, got {self.ms}")


Step = ClickStep | KeyStep | WaitStep


@dataclass
class Profile:
    """
    A complete, runnable description.

    Two shapes live in this one type on purpose. Simple mode is the four fields a user asked for
    (interval, count, start time, button); advanced mode is an explicit step sequence. Both are
    compiled to the same `steps` + schedule by one function, because two schedulers would eventually
    disagree about what "500 ms" means.
    """

    name: str = "default"
    enabled: bool = True

    # --- simple mode -----------------------------------------------------
    mode: Literal["simple", "advanced"] = "simple"
    interval_ms: int = 100
    repeat: int = 0           # 0 means unlimited
    start_at: str = ""        # "HH:MM:SS" local, empty means "start immediately"
    start_in_ms: int = 0      # alternative: start after this many ms
    button: MouseButton = "left"
    position: PositionMode = "cursor"
    x: int = 0
    y: int = 0
    at_once: int = 1
    double: bool = False

    # --- advanced mode ---------------------------------------------------
    steps: list[Step] = field(default_factory=list)

    # --- shared ----------------------------------------------------------
    # Stop automatically after this many ms of running, 0 = never. A safety net for "I started it
    # and walked away".
    max_duration_ms: int = 0
    hotkey: str = "f6"

    # The force stop key: pressed once during a run, it stops immediately from inside the keyboard hook
    # rather than through the interface, so it works even if the window is not responding. Bare Enter by
    # default because that is what was asked for: no modifier to find in a hurry.
    force_stop_key: str = "enter"
    # While a run is active, hold the key back so the panic button cannot also submit a form or send a
    # message in whatever has focus. The key works normally again as soon as the run ends.
    force_stop_swallow: bool = True

    def validate(self) -> None:
        if self.mode not in ("simple", "advanced"):
            raise ProfileError(f"unknown mode: {self.mode!r}")
        if not (MIN_INTERVAL_MS <= self.interval_ms <= MAX_INTERVAL_MS):
            raise ProfileError(f"interval must be 0..{MAX_INTERVAL_MS} ms, got {self.interval_ms}")
        if not (0 <= self.repeat <= MAX_REPEAT):
            raise ProfileError(f"count must be 0..{MAX_REPEAT} (0 = unlimited), got {self.repeat}")
        if not (0 <= self.start_in_ms <= MAX_INTERVAL_MS):
            raise ProfileError(f"start delay must be 0..{MAX_INTERVAL_MS} ms, got {self.start_in_ms}")
        if not (0 <= self.max_duration_ms <= MAX_INTERVAL_MS):
            raise ProfileError(f"max duration must be 0..{MAX_INTERVAL_MS} ms, got {self.max_duration_ms}")
        if self.start_at:
            try:
                parse_clock(self.start_at)
            except ParseError as e:
                # the caller of validate() wants a ProfileError; the message is the parser's
                raise ProfileError(f"start time: {e}") from None
        if self.force_stop_key:
            try:
                # Resolve the name NOW rather than at the moment of panic. An unusable name must be
                # reported when the setting is made, not discovered while trying to stop a runaway run.
                from .wininput import key_to_vk

                key_to_vk(self.force_stop_key)
            except Exception as e:  # noqa: BLE001
                raise ProfileError(f"force stop key: {e}") from None
        if self.mode == "simple":
            ClickStep(
                button=self.button, position=self.position, x=self.x, y=self.y,
                at_once=self.at_once, double=self.double,
            ).validate()
        else:
            if not self.steps:
                raise ProfileError("advanced mode needs at least one step")
            if len(self.steps) > MAX_STEPS:
                raise ProfileError(f"at most {MAX_STEPS} steps, got {len(self.steps)}")
            for i, s in enumerate(self.steps):
                try:
                    s.validate()
                except ProfileError as e:
                    raise ProfileError(f"step {i + 1}: {e}") from None

    # ------------------------------------------------------------------ compiled view

    def compile_steps(self) -> list[Step]:
        """
        The step sequence to execute once per repetition.

        Simple mode becomes a single click step; the interval is the gap between repetitions, not
        inside this list. Keeping that split means "click every 500 ms, 100 times" has exactly one
        place where 500 is interpreted.
        """
        self.validate()
        if self.mode == "simple":
            return [ClickStep(
                button=self.button, position=self.position, x=self.x, y=self.y,
                at_once=self.at_once, double=self.double,
            )]
        return list(self.steps)

    def total_keys(self) -> int:
        return sum(len(s.keys) for s in self.compile_steps() if isinstance(s, KeyStep))

    def describe(self) -> str:
        """A one-line summary for the profile list."""
        if self.mode == "simple":
            count = "unlimited" if self.repeat == 0 else str(self.repeat)
            when = f", at {self.start_at}" if self.start_at else ""
            at = f"{self.at_once}x at once" if self.at_once > 1 else ""
            parts = [f"{self.button} click every {self.interval_ms} ms", f"count {count}"]
            if at:
                parts.append(at)
            return "; ".join(parts) + when
        kinds = [s.kind for s in self.steps]
        return f"{len(self.steps)} steps ({', '.join(kinds)})"


def _in_screen_range(x: int, y: int) -> bool:
    """
    Loose sanity bound for a captured coordinate.

    Deliberately wide: multi-monitor setups with negative origins and large virtual desktops are
    normal, and a tight guess would reject valid points. This only catches values that cannot be a
    screen coordinate at all.
    """
    return -32_768 <= x <= 32_767 and -32_768 <= y <= 32_767


def normalise_clock(text: str) -> str:
    """
    Reduce whatever the user typed to a bare "HH:MM:SS"-shaped string.

    Accepts "11:50", "11:50:20", "11:50:20.5", and full timestamps such as
    "2026-01-02T11:50:20" or "2026-01-02 11:50:20" - people paste dates. Keeping this separate from
    parsing means the caller stores a value that always means the same thing: a time of day.
    """
    raw = (text or "").strip()
    if not raw:
        raise ParseError("time is empty")
    # a pasted timestamp: everything after 'T', or after the first space
    if "T" in raw:
        raw = raw.split("T", 1)[1]
    elif " " in raw:
        parts = raw.split(" ", 1)[1].strip()
        if parts:
            raw = parts
    # strip a timezone suffix, which we cannot honour anyway (local time is what the user means)
    for sep in ("+", "Z", "z"):
        if sep in raw:
            raw = raw.split(sep, 1)[0]
    return raw.strip()


def parse_clock(text: str) -> tuple[int, int, int]:
    """
    Parse "HH:MM", "HH:MM:SS" or "HH:MM:SS.mmm" into (h, m, s).

    Raises ParseError, not ProfileError: this is a parser, and a caller that catches the documented
    "the user typed something unreadable" error must catch this one too.
    """
    raw = normalise_clock(text)
    # allow a pasted date: take everything after the last space or 'T'
    if "T" in raw:
        raw = raw.split("T", 1)[1]
    elif " " in raw:
        raw = raw.split(" ", 1)[1].strip()
    raw = raw.split("+")[0].split("Z")[0].strip()

    bits = raw.split(":")
    if len(bits) not in (2, 3):
        raise ParseError(f"time must look like HH:MM or HH:MM:SS, got {text!r}")
    try:
        h = int(bits[0])
        m = int(bits[1])
        sec = float(bits[2]) if len(bits) == 3 else 0.0
    except ValueError:
        raise ParseError(f"time must be numbers separated by ':', got {text!r}") from None

    if not (0 <= h <= 23):
        raise ParseError(f"hour must be 0..23, got {h}")
    if not (0 <= m <= 59):
        raise ParseError(f"minute must be 0..59, got {m}")
    if not (0 <= sec < 60):
        raise ParseError(f"second must be 0..59.999, got {sec}")
    return h, m, int(sec)


def to_dict(profile: Profile) -> dict[str, Any]:
    """Serialise to plain JSON-compatible data. Step kinds are tagged so they round-trip exactly."""
    steps: list[dict[str, Any]] = []
    for s in profile.steps:
        if isinstance(s, ClickStep):
            steps.append({
                "kind": "click", "button": s.button, "position": s.position,
                "x": s.x, "y": s.y, "at_once": s.at_once, "double": s.double,
            })
        elif isinstance(s, KeyStep):
            steps.append({
                "kind": "key", "keys": list(s.keys),
                "gap_ms": s.gap_ms, "hold_ms": s.hold_ms,
            })
        elif isinstance(s, WaitStep):
            steps.append({"kind": "wait", "ms": s.ms})
        else:  # pragma: no cover - the union is closed
            raise ProfileError(f"cannot serialise step of type {type(s).__name__}")
    return {
        "name": profile.name,
        "enabled": profile.enabled,
        "mode": profile.mode,
        "interval_ms": profile.interval_ms,
        "repeat": profile.repeat,
        "start_at": profile.start_at,
        "start_in_ms": profile.start_in_ms,
        "button": profile.button,
        "position": profile.position,
        "x": profile.x,
        "y": profile.y,
        "at_once": profile.at_once,
        "double": profile.double,
        "steps": steps,
        "max_duration_ms": profile.max_duration_ms,
        "hotkey": profile.hotkey,
    }


def step_from_dict(d: Any) -> Step:
    """
    Rebuild a step, rejecting anything unrecognised.

    A silently-defaulted unknown step kind is how a profile becomes a no-op that the user cannot see
    is a no-op, so an unknown kind is an error, not a default.
    """
    if not isinstance(d, dict):
        raise ProfileError(f"a step must be an object, got {type(d).__name__}")
    kind = d.get("kind")
    if kind == "click":
        return ClickStep(
            button=str(d.get("button", "left")),           # type: ignore[arg-type]
            position=str(d.get("position", "cursor")),     # type: ignore[arg-type]
            x=int(d.get("x", 0)), y=int(d.get("y", 0)),
            at_once=int(d.get("at_once", 1)), double=bool(d.get("double", False)),
        )
    if kind == "key":
        keys = d.get("keys", [])
        if not isinstance(keys, list):
            raise ProfileError("a key step's 'keys' must be a list")
        return KeyStep(
            keys=[str(k) for k in keys],
            gap_ms=int(d.get("gap_ms", 30)), hold_ms=int(d.get("hold_ms", 0)),
        )
    if kind == "wait":
        return WaitStep(ms=int(d.get("ms", 100)))
    raise ProfileError(f"unknown step kind: {kind!r}")


def from_dict(d: Any) -> Profile:
    """Rebuild a profile from stored data. Unknown keys are ignored so older files keep loading."""
    if not isinstance(d, dict):
        raise ProfileError(f"a profile must be an object, got {type(d).__name__}")
    raw_steps = d.get("steps") or []
    if not isinstance(raw_steps, list):
        raise ProfileError("'steps' must be a list")
    p = Profile(
        name=str(d.get("name", "default"))[:64],
        enabled=bool(d.get("enabled", True)),
        mode=str(d.get("mode", "simple")),                 # type: ignore[arg-type]
        interval_ms=int(d.get("interval_ms", 100)),
        repeat=int(d.get("repeat", 0)),
        start_at=str(d.get("start_at", "")),
        start_in_ms=int(d.get("start_in_ms", 0)),
        button=str(d.get("button", "left")),               # type: ignore[arg-type]
        position=str(d.get("position", "cursor")),         # type: ignore[arg-type]
        x=int(d.get("x", 0)), y=int(d.get("y", 0)),
        at_once=int(d.get("at_once", 1)), double=bool(d.get("double", False)),
        steps=[step_from_dict(s) for s in raw_steps],
        max_duration_ms=int(d.get("max_duration_ms", 0)),
        hotkey=str(d.get("hotkey", "f6")),
    )
    p.validate()
    return p
