#!/usr/bin/env python3
"""
Change the force stop key default from Enter to Escape.

The reason this is a script rather than one edit: the string "enter" appeared as a hardcoded fallback
in nine places across three files. Changing the default meant changing all nine, and any one missed
would leave a path that silently still used Enter - for instance the label text would say ESC while the
hook watched Enter.

So the change is also a fix: a single DEFAULT_FORCE_STOP_KEY constant, and every fallback refers to it.
Changing the default again is now one edit.
"""
from __future__ import annotations

import pathlib
import re

SRC = pathlib.Path("/root/autoclicker/src/autoclick")
TESTS = pathlib.Path("/root/autoclicker/tests")
changed: list[str] = []


def edit(path: pathlib.Path, pairs: list[tuple[str, str]], *, required: bool = True) -> None:
    text = path.read_text()
    original = text
    for old, new in pairs:
        if old not in text:
            if required:
                raise SystemExit(f"NOT FOUND in {path.name}: {old[:70]!r}")
            continue
        text = text.replace(old, new)
    if text != original:
        path.write_text(text)
        changed.append(path.name)


# --- 1. the constant lives with the model, since the model is what defines the default ---------------
edit(SRC / "core" / "model.py", [
    (
        '''    # The force stop key: pressed once during a run, it stops immediately from inside the keyboard hook
    # rather than through the interface, so it works even if the window is not responding. Bare Enter by
    # default because that is what was asked for: no modifier to find in a hurry.
    force_stop_key: str = "enter"''',
        '''    # The force stop key: pressed once during a run, it stops immediately from inside the keyboard hook
    # rather than through the interface, so it works even if the window is not responding. No modifier to
    # find in a hurry.
    #
    # Escape, not Enter. Both are single keys with no modifier, but Escape already means "stop" in games
    # and full-screen applications, and it is far less likely to be the key you are using for something
    # else at the moment you need to stop. Enter is used constantly; Escape is used when you want out.
    force_stop_key: str = DEFAULT_FORCE_STOP_KEY''',
    ),
])

# the constant itself
text = (SRC / "core" / "model.py").read_text()
if "DEFAULT_FORCE_STOP_KEY" not in text.split("class Profile")[0]:
    text = text.replace(
        "MAX_STEPS = 500",
        'MAX_STEPS = 500\n\n# The force stop key. One definition, because this string is used as a fallback in several places and\n# a divergent copy would leave a path watching the wrong key while the label said otherwise.\nDEFAULT_FORCE_STOP_KEY = "esc"',
        1,
    )
    (SRC / "core" / "model.py").write_text(text)
    changed.append("model.py (constant)")

# --- 2. every hardcoded fallback now refers to the constant ------------------------------------------
for name in ("ui/app.py", "__main__.py"):
    path = SRC / name
    text = path.read_text()

    # make the import available
    if "DEFAULT_FORCE_STOP_KEY" in text and "DEFAULT_FORCE_STOP_KEY" not in text.split("\n\nclass ")[0]:
        if name == "ui/app.py":
            text = text.replace(
                "from ..core.model import MAX_AT_ONCE, ClickStep, KeyStep, Profile, WaitStep",
                "from ..core.model import (\n    DEFAULT_FORCE_STOP_KEY,\n    MAX_AT_ONCE,\n    ClickStep,\n    KeyStep,\n    Profile,\n    WaitStep,\n)",
                1,
            )
    path.write_text(text)

# replace the fallbacks
edit(SRC / "ui" / "app.py", [
    ('key_name=self.current.force_stop_key or "enter",',
     "key_name=self.current.force_stop_key or DEFAULT_FORCE_STOP_KEY,"),
    ('self.v_force_key = tk.StringVar(value=self.current.force_stop_key or "enter")',
     "self.v_force_key = tk.StringVar(\n            value=self.current.force_stop_key or DEFAULT_FORCE_STOP_KEY\n        )"),
    ('force_stop_key=(self.v_force_key.get() or "enter").strip(),',
     "force_stop_key=(self.v_force_key.get() or DEFAULT_FORCE_STOP_KEY).strip(),"),
    ('self.v_force_key.set(p.force_stop_key or "enter")',
     "self.v_force_key.set(p.force_stop_key or DEFAULT_FORCE_STOP_KEY)"),
    ('self.force_watcher._target_vk = _resolve_force_key(profile.force_stop_key or "enter")',
     "self.force_watcher._target_vk = _resolve_force_key(\n            profile.force_stop_key or DEFAULT_FORCE_STOP_KEY\n        )"),
    ('text=self.tr("f.force_stop_armed").format(key=(profile.force_stop_key or "enter").upper()),',
     'text=self.tr("f.force_stop_armed").format(\n                    key=(profile.force_stop_key or DEFAULT_FORCE_STOP_KEY).upper()\n                ),'),
    ('key=(self.current.force_stop_key or "enter").upper()),',
     "key=(self.current.force_stop_key or DEFAULT_FORCE_STOP_KEY).upper()\n            ),"),
    ('        return key_to_vk("enter")',
     "        return key_to_vk(DEFAULT_FORCE_STOP_KEY)"),
])

edit(SRC / "__main__.py", [
    ('        return key_to_vk(name or "enter")',
     "        return key_to_vk(name or DEFAULT_FORCE_STOP_KEY)"),
    ('        return key_to_vk("enter")',
     "        return key_to_vk(DEFAULT_FORCE_STOP_KEY)"),
])

# the selftest imports it
t = (SRC / "__main__.py").read_text()
if "DEFAULT_FORCE_STOP_KEY" in t and "from autoclick.core.model import" not in t:
    t = t.replace(
        "    from autoclick.core.wininput import IS_WINDOWS, layout_report",
        "    from autoclick.core.model import DEFAULT_FORCE_STOP_KEY\n    from autoclick.core.wininput import IS_WINDOWS, layout_report",
        1,
    )
    (SRC / "__main__.py").write_text(t)
    changed.append("__main__.py (import)")

# --- 3. the tests that asserted ENTER ----------------------------------------------------------------
edit(TESTS / "test_ui.py", [
    ('        assert "ENTER" in app.force_label["text"].upper()',
     '        assert "ESC" in app.force_label["text"].upper()'),
])
# there are two identical assertions
t = (TESTS / "test_ui.py").read_text()
t = t.replace('assert "ENTER" in app.force_label["text"].upper()',
              'assert "ESC" in app.force_label["text"].upper()')
(TESTS / "test_ui.py").write_text(t)

edit(TESTS / "test_force_stop.py", [
    ("from autoclick.core.force_stop import (\n    HOOK_FIELD_OFFSETS,",
     "from autoclick.core.force_stop import (\n    HOOK_FIELD_OFFSETS,"),
], required=False)

print("changed:", ", ".join(changed))
print()
for f in [SRC / "core" / "model.py", SRC / "ui" / "app.py", SRC / "__main__.py"]:
    t = f.read_text()
    left = [m for m in re.finditer(r'or "enter"|"enter"\s*\)|key_to_vk\("enter"\)', t)]
    print(f"{f.name}: remaining hardcoded 'enter' fallbacks = {len(left)}")
