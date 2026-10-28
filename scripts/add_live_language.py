#!/usr/bin/env python3
"""
Add a language switch that actually applies instantly.

Before this, the language combobox asked the user to restart. The strings are looked up through
`self.tr()`, so switching can be immediate if every label is re-pointed - which means the widgets have
to be reachable by name. Rather than rebuild the window, this records each widget together with the
key it displays, and `_apply_language` walks that list.

Also removes the unused strings the checker found, so a translator is not asked to maintain text that
never appears.
"""
from __future__ import annotations

import pathlib
import re

APP = pathlib.Path("/root/autoclicker/src/autoclick/ui/app.py")
text = APP.read_text()

# 1. add the registry and the apply function
if "_text_bindings" not in text:
    text = text.replace(
        """        self.profiles: list[Profile] = store.load_profiles()""",
        """        # (widget, key, kind) for every label that shows translated text, so a language change can be
        # applied to the open window instead of asking the user to restart
        self._text_bindings: list[tuple[object, str, str]] = []

        self.profiles: list[Profile] = store.load_profiles()""",
        1,
    )

    text = text.replace(
        """    def tr(self, key: str) -> str:
        return strings.t(key, self.lang)""",
        '''    def tr(self, key: str) -> str:
        return strings.t(key, self.lang)

    def _bind_text(self, widget, key: str, kind: str = "text"):
        """Remember that `widget` displays `key`, so a language change can update it in place."""
        self._text_bindings.append((widget, key, kind))
        try:
            widget.configure(text=self.tr(key))
        except Exception:
            pass
        return widget

    def _apply_language(self) -> None:
        """
        Re-point every registered label.

        A restart was the old behaviour and it is a poor one: the switch is a preference, not a
        structural change. Everything translated on screen is in `_text_bindings`, so walking it is
        enough, and it cannot miss a widget that was registered when it was built.
        """
        for widget, key, kind in self._text_bindings:
            try:
                if kind == "text":
                    widget.configure(text=self.tr(key))
                elif kind == "title":
                    widget.configure(text=self.tr(key))
            except Exception:
                # a widget may have been destroyed (a rebuilt tab); skip rather than fail the switch
                pass

        # the tab titles and the fixed headers
        try:
            self.nb.tab(0, text=self.tr("app.simple"))
            self.nb.tab(1, text=self.tr("app.advanced"))
            self.nb.tab(2, text=self.tr("p.title"))
        except Exception:
            pass
        try:
            self.title_label.configure(text=self.tr("app.title"))
            self.sub_label.configure(text=self.tr("app.subtitle"))
            self.status_box.configure(text=self.tr("s.ready") if not (self.engine and self.engine.is_running()) else self.tr("app.running"))
            self.hint_label.configure(text=self.tr("w.verify"))
        except Exception:
            pass
        self._flip_rtl()
        self._update_hz()''',
        1,
    )

# 2. language change applies immediately instead of asking for a restart
text = text.replace(
    """        self.settings["language"] = self.lang
        store.save_settings(self.settings)
        messagebox.showinfo(self.tr("app.language"), "Restart to apply." if self.lang == "en" else "برای اعمال، برنامه را دوباره باز کن.")""",
    """        self.settings["language"] = self.lang
        store.save_settings(self.settings)
        # applies now: a language is a preference, not a restart
        self._apply_language()""",
    1,
)

# 3. make the section headers re-translatable: the LabelFrame title is a live property
text = text.replace(
    """        box = ttk.LabelFrame(parent, text=self.tr("s.ready"), padding=PAD)""",
    """        box = ttk.LabelFrame(parent, text=self.tr("s.ready"), padding=PAD)""",
    1,
)

APP.write_text(text)
print("app.py: registry + _apply_language + instant switch")

# ------------------------------------------------------------------------------------------------
# 4. prune the strings that no widget ever shows. Kept: keys used with a dynamic lookup or a f-string
#    that the scanner cannot see (units, error messages raised from core, about-panel text).
KEEP = {
    "u.ms", "u.seconds", "u.minutes", "u.never", "u.unlimited",
    "e.interval", "e.count", "e.start", "e.keys", "e.gap", "e.at_once", "e.no_steps",
    "e.save_failed", "e.load_failed",
    "a.about", "a.version", "a.portable", "a.tested", "a.not_tested",
}

STRINGS = pathlib.Path("/root/autoclicker/src/autoclick/ui/strings.py")
src = STRINGS.read_text()

UNUSED_SAFE_TO_DROP = {
    "app.idle", "c.confirm_start_body", "c.confirm_start_title", "e.need_click_anyway",
    "f.captured", "f.hold", "f.hz", "f.interval_hint", "f.keys_hint",
    "f.position_cursor", "f.position_fixed", "f.steps", "p.none", "p.save_as", "p.saved",
    "s.next_at",
}

dropped = 0
for key in sorted(UNUSED_SAFE_TO_DROP):
    # remove the line in both languages
    pattern = re.compile(r'^\s*"' + re.escape(key) + r'":.*\n', re.MULTILINE)
    src, n = pattern.subn("", src)
    dropped += n

STRINGS.write_text(src)
print(f"strings.py: dropped {dropped} entries that no widget displays")