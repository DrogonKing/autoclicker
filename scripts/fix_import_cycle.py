#!/usr/bin/env python3
"""
Fix the import cycle I introduced.

`ParseError` was defined in engine.py while both model.py and schedule.py needed it, and engine.py
imports both. It now lives in errors.py. This script rewrites the references rather than doing it by
hand, because a missed one is an ImportError at runtime, in the packaged build, on a user's machine.

It also removes the module-level monkey-patch that made `Schedule.for_profile` work: a Protocol with
a staticmethod attached after class creation is not a protocol method, and the engine should call a
plain function instead.
"""
import pathlib
import re

ROOT = pathlib.Path("/root/autoclicker/src/autoclick/core")

# --- model.py: take ProfileError from errors, do not define it ------------------------------------
p = ROOT / "model.py"
s = p.read_text()
s = s.replace(
    '''class ProfileError(ValueError):
    """A profile that cannot be run, with a message meant for a person."""


''',
    "",
)
s = s.replace(
    "from typing import Any, Literal",
    "from typing import Any, Literal\n\nfrom .errors import ProfileError",
)
p.write_text(s)
print("model.py: ProfileError now imported")

# --- schedule.py: use ParseError from errors, call a factory function -----------------------------
p = ROOT / "schedule.py"
s = p.read_text()
s = s.replace(
    "from .model import Profile\n",
    "from .errors import ParseError\nfrom .model import Profile\n",
)
s = s.replace(
    '''    def is_done(self, index: int, elapsed_ms: int) -> bool: ...

    @staticmethod
    def for_profile(profile: Profile) -> "Schedule": ...''',
    '''    def is_done(self, index: int, elapsed_ms: int) -> bool: ...''',
)
# drop the in-function imports that existed only to dodge the cycle
s = s.replace("    from .engine import ParseError\n\n", "")
s = s.replace("    from .engine import ParseError\n    from .model import parse_clock\n",
              "    from .model import parse_clock\n")
# drop the monkey-patch and provide a real factory
s = s.replace('''

# make Schedule usable as a static factory without an instance
Schedule.for_profile = staticmethod(  # type: ignore[attr-defined]
    lambda profile: (FixedInterval.for_profile(profile) if profile.interval_ms > 0 else BackToBack.for_profile(profile))
)
''', '''

def schedule_for(profile: Profile) -> Schedule:
    """
    The single place a profile becomes timing.

    An interval of 0 means "no waiting", which is a different schedule rather than a fast one: it
    skips the deadline arithmetic entirely, so a BackToBack run reports its achieved rate instead of
    an interval it was never holding to.
    """
    if profile.interval_ms > 0:
        return FixedInterval.for_profile(profile)
    return BackToBack.for_profile(profile)
''')
p.write_text(s)
print("schedule.py: ParseError imported, factory extracted")

# --- engine.py: drop its own ParseError, use the factory ------------------------------------------
p = ROOT / "engine.py"
s = p.read_text()
s = s.replace(
    "from .model import ClickStep, KeyStep, Profile, ProfileError, Step, WaitStep\nfrom .schedule import Schedule, parse_duration, parse_start_time",
    "from .errors import ParseError, ProfileError\nfrom .model import ClickStep, KeyStep, Profile, Step, WaitStep\nfrom .schedule import Schedule, parse_duration, parse_start_time, schedule_for",
)
s = s.replace(
    '''# Re-exported so callers do not need to know which module owns them.
__all__ = ["Engine", "InputBackend", "RunStats", "ParseError", "parse_start_time",
           "parse_duration", "Schedule"]


class ParseError(ValueError):
    """A value the user typed that could not be understood."""
''',
    '''# Re-exported so callers do not need to know which module owns them.
__all__ = ["Engine", "InputBackend", "RunStats", "ParseError", "ProfileError",
           "parse_start_time", "parse_duration", "Schedule"]
''',
)
s = s.replace(
    "        return Schedule.for_profile(profile)",
    "        return schedule_for(profile)",
)
p.write_text(s)
print("engine.py: uses errors.ParseError and the factory")

# --- verify no stale references remain ------------------------------------------------------------
problems = []
for f in ROOT.glob("*.py"):
    text = f.read_text()
    if re.search(r"from \.engine import ParseError", text):
        problems.append(f"{f.name}: still imports ParseError from engine")
    if "Schedule.for_profile" in text:
        problems.append(f"{f.name}: still calls Schedule.for_profile")
    if "class ProfileError" in text and f.name != "errors.py":
        problems.append(f"{f.name}: defines ProfileError instead of importing it")
    if "class ParseError" in text and f.name != "errors.py":
        problems.append(f"{f.name}: defines ParseError instead of importing it")

print()
if problems:
    for x in problems:
        print("  PROBLEM:", x)
    raise SystemExit(1)
print("  no stale references")
