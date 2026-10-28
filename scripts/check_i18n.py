#!/usr/bin/env python3
"""
Check that every translation key the UI asks for actually exists.

A missing key falls back to the key name itself, so a Persian user would see "f.interval" where a
label should be. That is visible but easy to miss in review, and trivial to check mechanically.
Also reports keys that are defined but never used, which are dead weight in both languages.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from autoclick.ui.strings import STRINGS  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Collect every `self.tr("...")` and `t("...")` literal in the UI.
used: set[str] = set()
for path in list((ROOT / "src" / "autoclick" / "ui").glob("*.py")) + \
            list((ROOT / "src" / "autoclick").glob("*.py")):
    text = path.read_text(encoding="utf-8")
    for m in re.finditer(r"""\btr\(\s*["']([a-zA-Z0-9_.]+)["']""", text):
        used.add(m.group(1))
    for m in re.finditer(r"""\bt\(\s*["']([a-zA-Z0-9_.]+)["']""", text):
        used.add(m.group(1))
    # keys passed to helpers rather than to tr() directly: label builders, the stat grid, bindings
    # Quoted strings inside the call to a helper, filtered to the shape a key has: a dot, and no '#'
    # (which is how a colour like "#666" is written). A plain regex cannot distinguish the two, and
    # guessing wrong reports a colour as a missing translation.
    for m in re.finditer(r"""_(?:labelled|bind_text)\(([^;]*?)\)""", text, re.S):
        for candidate in re.findall(r"""["']([a-zA-Z0-9_.]+)["']""", m.group(1)):
            if "." in candidate and "#" not in candidate:
                used.add(candidate)
    # the status grid iterates a tuple of keys
    for m in re.finditer(r'for\s+\w+,\s*\w+\s+in\s+enumerate\(\(([^)]*)\)\)', text):
        for k in re.findall(r'"([a-zA-Z0-9_.]+)"', m.group(1)):
            used.add(k)

defined_en = set(STRINGS["en"])
defined_fa = set(STRINGS["fa"])

print(f"keys used in code : {len(used)}")
print(f"keys defined (en) : {len(defined_en)}")
print(f"keys defined (fa) : {len(defined_fa)}")
print()

missing = sorted(used - defined_en)
print("USED BUT NOT DEFINED:", missing if missing else "none")

only_en = sorted(defined_en - defined_fa)
only_fa = sorted(defined_fa - defined_en)
print("in EN but not FA:", only_en if only_en else "none")
print("in FA but not EN:", only_fa if only_fa else "none")

# Not shown by a widget, so a source scan cannot see them:
#   e.*  mirror the messages raised by core (kept in step with core/errors.py wording)
#   u.*  unit words, used when formatting a value for display
RESERVED_PREFIXES = ("e.", "u.")
# Exceptions, each for a stated reason rather than to silence the check:
#   a.*          the About panel builds its text from f-strings and layout_report()
#   app.language the label's key sits outside ttk.Label(...), past where the scan looks
RESERVED_KEYS = {"a.about", "a.version", "a.portable", "a.tested", "a.not_tested", "app.language"}
unused = sorted(
    k for k in (defined_en - used)
    if not k.startswith(RESERVED_PREFIXES) and k not in RESERVED_KEYS
)
print("defined but unused:", unused if unused else "none")

# An empty translation is worse than a missing one: it renders as nothing at all.
empties = sorted(k for lang in STRINGS for k, v in STRINGS[lang].items() if not str(v).strip())
print("empty translations:", empties if empties else "none")

# Placeholders must match between languages, or a formatted string raises at the worst moment.
mismatched: list[str] = []
for key in defined_en & defined_fa:
    a = set(re.findall(r"\{(\w+)\}", str(STRINGS["en"][key])))
    b = set(re.findall(r"\{(\w+)\}", str(STRINGS["fa"][key])))
    if a != b:
        mismatched.append(f"{key}: en={sorted(a)} fa={sorted(b)}")
print("placeholder mismatches:", mismatched if mismatched else "none")

problems = bool(missing or only_en or only_fa or empties or mismatched)
print()
print("RESULT:", "PROBLEMS FOUND" if problems else "all translation keys are consistent")
sys.exit(1 if problems else 0)
