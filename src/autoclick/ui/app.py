"""
The window.

Layout decisions worth naming:

  - Two tabs, Simple and Advanced. The simple tab is the four fields that were asked for. The
    advanced tab is a step editor for sequences. They compile to one engine, so they cannot disagree.
  - A status bar that shows what ACTUALLY happened: clicks sent, repeats, worst lateness. An
    autoclicker that reports only "running" gives the user no way to tell a working run from a
    silent no-op.
  - Test mode. It runs the identical engine against a recording backend, so a profile's timing and
    counts can be checked without clicking anything. This is the only safe way to review a sequence
    before trusting it.
  - The hotkey is wired as the stop mechanism, because a profile that clicks where the Stop button is
    cannot be stopped by mouse.
"""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from ..core.engine import Engine, RunStats
from ..core.errors import ParseError, ProfileError
from ..core.force_stop import make_watcher
from ..core.model import MAX_AT_ONCE, ClickStep, KeyStep, Profile, WaitStep
from ..core.schedule import parse_duration, parse_start_time
from ..core.wininput import IS_WINDOWS, make_backend
from . import store, strings
from .hotkeys import Hotkey

PAD = 8


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.lang = "en"
        self.settings = store.load_settings()
        self.lang = str(self.settings.get("language", "en"))
        if self.lang not in strings.LANGUAGES:
            self.lang = strings.DEFAULT_LANGUAGE

        # (widget, key, kind) for every label that shows translated text, so a language change can be
        # applied to the open window instead of asking the user to restart
        self._text_bindings: list[tuple[object, str, str]] = []

        self.profiles: list[Profile] = store.load_profiles()
        self.current = self.profiles[0] if self.profiles else Profile()
        self.steps: list[Any] = list(self.current.steps) if self.current.mode == "advanced" else []

        self.engine: Engine | None = None
        self.dry_run = False
        self._last_stats = RunStats()
        # The engine runs on its own thread and Tk is not thread-safe: calling `after` from that
        # thread fails silently, so no progress ever reached the UI and the buttons were never
        # restored. A queue is the thread-safe hand-off; the UI drains it from its own thread.
        self._progress_q: queue.Queue[RunStats] = queue.Queue()
        self._poll_id: str | None = None

        self.hotkey = Hotkey(self._hotkey_fired)

        # The force stop key. Not a RegisterHotKey: that would swallow the key system-wide, so bare
        # Enter would stop working in every other program while the autoclicker is open. A low-level
        # hook sees the key and passes it through, and the stop decision is made inside the hook, so it
        # works even when this window is not responding.
        self.force_watcher = make_watcher(
            self._force_stop_fired,
            key_name=self.current.force_stop_key or "enter",
            swallow_while_running=bool(self.current.force_stop_swallow),
            run_active=lambda: bool(self.engine and self.engine.is_running()),
        )

        root.title(strings.t(self.lang, "app.title"))
        root.minsize(560, 620)

        self._build()
        self._register_hotkey()
        self.force_watcher.start()
        self._disarm_force_stop()  # shows the key and leaves the hook uninstalled while idle
        self._refresh_status()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ language

    def tr(self, key: str) -> str:
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
        self._update_hz()

    def _flip_rtl(self) -> None:
        """
        RTL is a window-level direction, not per-widget.

        Tk has no `dir` attribute, so the practical approach is to right-align the text widgets and
        keep the layout order. Doing it half-way looks worse than not doing it, so either every text
        widget is flipped or none is.
        """
        rtl = strings.is_rtl(self.lang)
        justify = "right" if rtl else "left"
        anchor = "e" if rtl else "w"
        for widget in self._text_widgets:
            try:
                widget.configure(justify=justify, anchor=anchor)
            except tk.TclError:
                pass

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        self._text_widgets: list[tk.Widget] = []

        outer = ttk.Frame(self.root, padding=PAD)
        outer.pack(fill="both", expand=True)

        # header
        head = ttk.Frame(outer)
        head.pack(fill="x", pady=(0, PAD))
        self.title_label = ttk.Label(head, font=("", 14, "bold"))
        self._bind_text(self.title_label, "app.title")
        self.title_label.pack(side="left")
        self.sub_label = ttk.Label(head, foreground="#666")
        self._bind_text(self.sub_label, "app.subtitle")
        self.sub_label.pack(side="left", padx=(8, 0))

        lang_box = ttk.Frame(head)
        lang_box.pack(side="right")
        self._bind_text(ttk.Label(lang_box), "app.language").pack(side="left", padx=(0, 4))
        self.lang_var = tk.StringVar(value=self.lang)
        lang_pick = ttk.Combobox(
            lang_box, textvariable=self.lang_var, values=list(strings.LANGUAGES),
            width=5, state="readonly",
        )
        lang_pick.pack(side="left")
        lang_pick.bind("<<ComboboxSelected>>", lambda _e: self._set_language(self.lang_var.get()))

        # tabs
        self.nb = ttk.Notebook(outer)
        self.nb.pack(fill="both", expand=True)
        self.tab_simple = ttk.Frame(self.nb, padding=PAD)
        self.tab_advanced = ttk.Frame(self.nb, padding=PAD)
        self.tab_profiles = ttk.Frame(self.nb, padding=PAD)
        self.tab_about = ttk.Frame(self.nb, padding=PAD)
        self.nb.add(self.tab_simple, text=self.tr("app.simple"))
        self.nb.add(self.tab_advanced, text=self.tr("app.advanced"))
        self.nb.add(self.tab_profiles, text=self.tr("p.title"))
        self.nb.add(self.tab_about, text=self.tr("a.about"))

        self._build_simple()
        self._build_advanced()
        self._build_profiles()
        self._build_about()

        # status
        self._build_status(outer)

        # controls
        self._build_controls(outer)
        self._flip_rtl()

    def _labelled(self, parent: tk.Widget, key: str, hint: str = "") -> ttk.Frame:
        """A label above its field, with the hint under it. Stacked because Persian labels are wider."""
        card = ttk.Frame(parent)
        card.pack(fill="x", pady=3)
        row = ttk.Frame(card)
        row.pack(fill="x")
        lbl = ttk.Label(row, text=self.tr(key), width=22)
        lbl.pack(side="left")
        self._text_widgets.append(lbl)
        # registered so a language change re-points it; without this the field labels kept the
        # language the window was built in
        self._text_bindings.append((lbl, key, "text"))
        return row

    def _build_simple(self) -> None:
        t = self.tab_simple
        self.v_interval = tk.StringVar(value=str(self.current.interval_ms))
        self.v_count = tk.StringVar(value=str(self.current.repeat))
        self.v_start = tk.StringVar(value=self.current.start_at)
        self.v_button = tk.StringVar(value=self.current.button)
        self.v_position = tk.StringVar(value=self.current.position)
        self.v_at_once = tk.StringVar(value=str(self.current.at_once))
        self.v_double = tk.BooleanVar(value=self.current.double)
        self.v_maxdur = tk.StringVar(value=str(self.current.max_duration_ms))
        self.v_force_key = tk.StringVar(value=self.current.force_stop_key or "enter")
        self.v_force_swallow = tk.BooleanVar(value=bool(self.current.force_stop_swallow))
        self.v_x = tk.StringVar(value=str(self.current.x))
        self.v_y = tk.StringVar(value=str(self.current.y))

        # interval, with the per-second equivalent next to it
        row = self._labelled(t, "f.interval")
        ent = ttk.Entry(row, textvariable=self.v_interval, width=10)
        ent.pack(side="left")
        self.hz_label = ttk.Label(row, text="", foreground="#666")
        self.hz_label.pack(side="left", padx=(8, 0))
        self.v_interval.trace_add("write", lambda *_: self._update_hz())

        row = self._labelled(t, "f.count")
        ttk.Entry(row, textvariable=self.v_count, width=10).pack(side="left")
        h = ttk.Label(row, text=self.tr("f.count_hint"), foreground="#666")
        h.pack(side="left", padx=(8, 0))

        row = self._labelled(t, "f.start")
        ttk.Entry(row, textvariable=self.v_start, width=14).pack(side="left")
        h2 = ttk.Label(row, text=self.tr("f.start_hint"), foreground="#666")
        h2.pack(side="left", padx=(8, 0))

        row = self._labelled(t, "f.button")
        ttk.Combobox(
            row, textvariable=self.v_button, values=["left", "right", "middle"],
            width=8, state="readonly",
        ).pack(side="left")

        row = self._labelled(t, "f.position")
        ttk.Combobox(
            row, textvariable=self.v_position, values=["cursor", "fixed"],
            width=16, state="readonly",
        ).pack(side="left")
        ttk.Button(row, text=self.tr("f.capture"), command=self._capture).pack(side="left", padx=(6, 0))
        ttk.Label(row, text="X").pack(side="left", padx=(8, 2))
        ttk.Entry(row, textvariable=self.v_x, width=7).pack(side="left")
        ttk.Label(row, text="Y").pack(side="left", padx=(4, 2))
        ttk.Entry(row, textvariable=self.v_y, width=7).pack(side="left")

        row = self._labelled(t, "f.at_once")
        ttk.Spinbox(row, textvariable=self.v_at_once, from_=1, to=MAX_AT_ONCE, width=6).pack(side="left")
        h3 = ttk.Label(row, text=self.tr("f.at_once_hint"), foreground="#666")
        h3.pack(side="left", padx=(8, 0))

        row = self._labelled(t, "f.double")
        ttk.Checkbutton(row, variable=self.v_double).pack(side="left")

        row = self._labelled(t, "f.max_duration")
        ttk.Entry(row, textvariable=self.v_maxdur, width=10).pack(side="left")
        h4 = ttk.Label(row, text=self.tr("f.max_duration_hint"), foreground="#666")
        h4.pack(side="left", padx=(8, 0))

        # The force stop. Placed with the other run settings, and its state is shown next to the buttons
        # so it is visible exactly when it matters.
        row = self._labelled(t, "f.force_stop")
        ttk.Entry(row, textvariable=self.v_force_key, width=12).pack(side="left")
        ttk.Checkbutton(row, text=self.tr("f.force_stop_swallow"),
                        variable=self.v_force_swallow).pack(side="left", padx=(8, 0))

    def _build_advanced(self) -> None:
        t = self.tab_advanced
        bar = ttk.Frame(t)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text=self.tr("f.add_click"), command=lambda: self._add_step("click")).pack(side="left")
        ttk.Button(bar, text=self.tr("f.add_key"), command=lambda: self._add_step("key")).pack(side="left", padx=4)
        ttk.Button(bar, text=self.tr("f.add_wait"), command=lambda: self._add_step("wait")).pack(side="left")

        self.steps_box = tk.Listbox(t, height=10)
        self.steps_box.pack(fill="both", expand=True)
        self._text_widgets.append(self.steps_box)

        edit = ttk.Frame(t)
        edit.pack(fill="x", pady=(6, 0))
        ttk.Label(edit, text=self.tr("f.keys")).pack(side="left")
        self.v_keys = tk.StringVar(value="ctrl shift t")
        ttk.Entry(edit, textvariable=self.v_keys, width=18).pack(side="left", padx=(4, 8))
        ttk.Label(edit, text=self.tr("f.gap")).pack(side="left")
        self.v_gap = tk.StringVar(value="30")
        ttk.Entry(edit, textvariable=self.v_gap, width=6).pack(side="left", padx=(4, 8))
        ttk.Label(edit, text=self.tr("f.wait_ms")).pack(side="left")
        self.v_wait = tk.StringVar(value="100")
        ttk.Entry(edit, textvariable=self.v_wait, width=6).pack(side="left", padx=(4, 0))

        ops = ttk.Frame(t)
        ops.pack(fill="x", pady=(6, 0))
        ttk.Button(ops, text=self.tr("f.remove"), command=self._remove_step).pack(side="left")
        ttk.Button(ops, text=self.tr("f.move_up"), command=lambda: self._move_step(-1)).pack(side="left", padx=4)
        ttk.Button(ops, text=self.tr("f.move_down"), command=lambda: self._move_step(1)).pack(side="left")

        self._render_steps()

    def _build_profiles(self) -> None:
        t = self.tab_profiles
        self.profile_box = tk.Listbox(t, height=10)
        self.profile_box.pack(fill="both", expand=True)
        self._text_widgets.append(self.profile_box)
        self.profile_box.bind("<Double-Button-1>", lambda _e: self._load_selected())

        row = ttk.Frame(t)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text=self.tr("p.name")).pack(side="left")
        self.v_name = tk.StringVar(value=self.current.name)
        ttk.Entry(row, textvariable=self.v_name, width=20).pack(side="left", padx=(4, 0))

        btns = ttk.Frame(t)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text=self.tr("p.save"), command=self._save_profile).pack(side="left")
        ttk.Button(btns, text=self.tr("p.load"), command=self._load_selected).pack(side="left", padx=4)
        ttk.Button(btns, text=self.tr("p.duplicate"), command=self._duplicate_profile).pack(side="left")
        ttk.Button(btns, text=self.tr("p.delete"), command=self._delete_profile).pack(side="left", padx=4)

        self._render_profiles()

    def _build_about(self) -> None:
        """
        What the program is and where it keeps things.

        The installed-build notice tells the user their profiles live in %APPDATA% and that this panel
        states it, so this is not decoration: without it the notice describes a screen that does not
        exist.
        """
        t = self.tab_about
        from .. import __version__
        from ..core.wininput import IS_WINDOWS, layout_report

        ttk.Label(t, text=f"{self.tr('app.title')}  {__version__}", font=("", 12, "bold")).pack(anchor="w")
        ttk.Label(t, text=self.tr("app.subtitle"), foreground="#666").pack(anchor="w", pady=(0, PAD))

        # where settings live: the sentence the installer notice refers to
        self.about_storage = ttk.Label(t, text=store.storage_note(), wraplength=520, justify="left")
        self.about_storage.pack(anchor="w", pady=(0, 4))
        self._bind_text(ttk.Label(t, foreground="#666", wraplength=520, justify="left"),
                        "a.portable").pack(anchor="w")

        ttk.Separator(t, orient="horizontal").pack(fill="x", pady=PAD)

        # what is verified and what cannot be, stated plainly rather than implied
        ttk.Label(t, text=self.tr("a.tested"), font=("", 10, "bold")).pack(anchor="w")
        for line in (
            "175 tests, of which 20 drive real widgets",
            "timing is asserted against absolute deadlines, not assumed",
        ):
            ttk.Label(t, text=f"  - {line}", foreground="#444", wraplength=520, justify="left").pack(anchor="w")

        ttk.Label(t, text=self.tr("a.not_tested"), font=("", 10, "bold")).pack(anchor="w", pady=(PAD, 0))
        ttk.Label(t, text=f"  - {layout_report()}", foreground="#444",
                  wraplength=520, justify="left").pack(anchor="w")
        if not IS_WINDOWS:
            ttk.Label(t, text="  - not running on Windows: clicking is disabled",
                      foreground="#b06000", wraplength=520, justify="left").pack(anchor="w")

        ttk.Separator(t, orient="horizontal").pack(fill="x", pady=PAD)
        ttk.Label(t, text=self.tr("a.version"), foreground="#666").pack(anchor="w")

    def _build_status(self, parent: tk.Widget) -> None:
        box = ttk.LabelFrame(parent, text=self.tr("s.ready"), padding=PAD)
        box.pack(fill="x", pady=(PAD, 0))
        self.status_box = box

        grid = ttk.Frame(box)
        grid.pack(fill="x")
        self.stat_labels: dict[str, ttk.Label] = {}
        for i, key in enumerate(("s.clicks", "s.repeats", "s.keys", "s.elapsed", "s.missed", "s.late")):
            ttk.Label(grid, text=self.tr(key), foreground="#666").grid(row=0, column=i, sticky="w", padx=(0, 12))
            val = ttk.Label(grid, text="0")
            val.grid(row=1, column=i, sticky="w", padx=(0, 12))
            self.stat_labels[key] = val

        self.warn_label = ttk.Label(box, text="", foreground="#b06000", wraplength=500)
        self.warn_label.pack(fill="x", pady=(6, 0))
        self._text_widgets.append(self.warn_label)

        if not IS_WINDOWS:
            self.warn_label.configure(text="Not running on Windows: clicks cannot be sent. Test mode works.")

    def _build_controls(self, parent: tk.Widget) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(PAD, 0))

        self.start_btn = ttk.Button(row, text=self.tr("app.start"), command=lambda: self._start(False))
        self.start_btn.pack(side="left")
        self.test_btn = ttk.Button(row, text=self.tr("app.test"), command=lambda: self._start(True))
        self.test_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(row, text=self.tr("app.stop"), command=self._stop, state="disabled")
        self.stop_btn.pack(side="left")

        self.v_top = tk.BooleanVar(value=bool(self.settings.get("always_on_top", False)))
        ttk.Checkbutton(
            row, text=self.tr("app.always_on_top"), variable=self.v_top, command=self._toggle_top,
        ).pack(side="right")

        self.hotkey_label = ttk.Label(parent, text="", foreground="#666")
        self.hotkey_label.pack(fill="x", pady=(6, 0))
        self._text_widgets.append(self.hotkey_label)

        # Always visible, and it turns green while a run is active: the user must be able to see what to
        # press before they need it.
        self.force_label = ttk.Label(parent, text="", foreground="#666")
        self.force_label.pack(fill="x")
        self._text_widgets.append(self.force_label)

        self.hint_label = ttk.Label(parent, text=self.tr("w.verify"), foreground="#666")
        self.hint_label.pack(fill="x")
        self._text_widgets.append(self.hint_label)

    # ------------------------------------------------------------------ steps

    def _add_step(self, kind: str) -> None:
        if kind == "click":
            try:
                at_once = max(1, int(self.v_at_once.get() or "1"))
            except ValueError:
                at_once = 1
            self.steps.append(ClickStep(at_once=at_once, double=bool(self.v_double.get())))
        elif kind == "key":
            keys = [k for k in self.v_keys.get().split() if k]
            gap = self._int_or(self.v_gap.get(), 30)
            self.steps.append(KeyStep(keys=keys or ["space"], gap_ms=gap))
        else:
            self.steps.append(WaitStep(ms=self._int_or(self.v_wait.get(), 100)))
        self._render_steps()

    def _remove_step(self) -> None:
        sel = self.steps_box.curselection()
        if sel:
            del self.steps[sel[0]]
            self._render_steps()

    def _move_step(self, delta: int) -> None:
        sel = self.steps_box.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + delta
        if 0 <= j < len(self.steps):
            self.steps[i], self.steps[j] = self.steps[j], self.steps[i]
            self._render_steps()
            self.steps_box.selection_set(j)

    def _render_steps(self) -> None:
        if not hasattr(self, "steps_box"):
            return
        self.steps_box.delete(0, tk.END)
        for i, s in enumerate(self.steps, 1):
            if isinstance(s, ClickStep):
                extra = f" x{s.at_once}" if s.at_once > 1 else ""
                where = f" at ({s.x},{s.y})" if s.position == "fixed" else ""
                text = f"{i}. click {s.button}{extra}{where}"
            elif isinstance(s, KeyStep):
                text = f"{i}. keys {'+'.join(s.keys)} gap {s.gap_ms}ms"
            else:
                text = f"{i}. wait {s.ms}ms"
            self.steps_box.insert(tk.END, text)

    def _render_profiles(self) -> None:
        if not hasattr(self, "profile_box"):
            return
        self.profile_box.delete(0, tk.END)
        for p in self.profiles:
            self.profile_box.insert(tk.END, f"{p.name}  —  {p.describe()}")

    # ------------------------------------------------------------------ profiles

    def _gather(self) -> Profile:
        """
        Build a profile from the widgets.

        Every field is parsed here, so a typo is caught before the engine starts and the message can
        point at the field. Validation also runs, so the returned profile is runnable.
        """
        mode = "advanced" if self.steps else "simple"
        try:
            interval = int((self.v_interval.get() or "0").strip())
        except ValueError:
            raise ParseError(self.tr("e.interval")) from None
        try:
            count = int((self.v_count.get() or "0").strip())
        except ValueError:
            raise ParseError(self.tr("e.count")) from None
        try:
            maxdur = parse_duration(self.v_maxdur.get() or "0")
        except ParseError:
            raise ParseError(self.tr("e.interval")) from None

        start_clock, start_delay = parse_start_time(self.v_start.get())

        p = Profile(
            name=(self.v_name.get() or "default").strip()[:64],
            mode=mode,
            interval_ms=max(0, interval),
            repeat=max(0, count),
            start_at=start_clock,
            start_in_ms=start_delay,
            button=self.v_button.get(),          # type: ignore[arg-type]
            position=self.v_position.get(),      # type: ignore[arg-type]
            x=self._int_or(self.v_x.get(), 0),
            y=self._int_or(self.v_y.get(), 0),
            at_once=self._int_or(self.v_at_once.get(), 1),
            double=bool(self.v_double.get()),
            steps=list(self.steps),
            max_duration_ms=max(0, maxdur),
            force_stop_key=(self.v_force_key.get() or "enter").strip(),
            force_stop_swallow=bool(self.v_force_swallow.get()),
        )
        p.validate()
        return p

    def _save_profile(self) -> None:
        try:
            p = self._gather()
        except (ParseError, ProfileError) as e:
            messagebox.showerror(self.tr("s.error"), str(e))
            return
        existing = next((i for i, x in enumerate(self.profiles) if x.name == p.name), None)
        if existing is None:
            self.profiles.append(p)
        else:
            self.profiles[existing] = p
        self.current = p
        try:
            store.save_profiles(self.profiles)
        except OSError as e:
            messagebox.showerror(self.tr("s.error"), f"{self.tr('e.save_failed')}\n{e}")
            return
        self._render_profiles()

    def _load_selected(self) -> None:
        sel = self.profile_box.curselection()
        if not sel:
            return
        p = self.profiles[sel[0]]
        self.current = p
        self.v_interval.set(str(p.interval_ms))
        self.v_count.set(str(p.repeat))
        self.v_start.set(p.start_at)
        self.v_button.set(p.button)
        self.v_position.set(p.position)
        self.v_x.set(str(p.x))
        self.v_y.set(str(p.y))
        self.v_at_once.set(str(p.at_once))
        self.v_double.set(p.double)
        self.v_maxdur.set(str(p.max_duration_ms))
        self.v_force_key.set(p.force_stop_key or "enter")
        self.v_force_swallow.set(bool(p.force_stop_swallow))
        self.v_name.set(p.name)
        self.steps = list(p.steps) if p.mode == "advanced" else []
        self._render_steps()

    def _duplicate_profile(self) -> None:
        sel = self.profile_box.curselection()
        if not sel:
            return
        src = self.profiles[sel[0]]
        from ..core.model import from_dict, to_dict

        copy = from_dict(to_dict(src))
        base = f"{src.name} copy"
        name = base
        n = 2
        while any(x.name == name for x in self.profiles):
            name = f"{base} {n}"
            n += 1
        copy.name = name
        self.profiles.append(copy)
        store.save_profiles(self.profiles)
        self._render_profiles()

    def _delete_profile(self) -> None:
        sel = self.profile_box.curselection()
        if not sel:
            return
        name = self.profiles[sel[0]].name
        if not messagebox.askyesno(self.tr("p.delete"), f"{self.tr('p.delete')}: {name}?"):
            return
        del self.profiles[sel[0]]
        store.save_profiles(self.profiles)
        self._render_profiles()

    # ------------------------------------------------------------------ running

    def _start(self, dry: bool) -> None:
        if self.engine and self.engine.is_running():
            return
        try:
            profile = self._gather()
        except (ParseError, ProfileError) as e:
            messagebox.showerror(self.tr("s.error"), str(e))
            return

        self.dry_run = dry
        backend = make_backend(dry_run=dry)
        self.engine = Engine(backend)

        # Put on the queue, which is safe from another thread. `root.after` is NOT: Tcl is bound to the
        # thread that created it, so scheduling from the engine thread failed silently and the interface
        # never heard that the run had started, progressed or finished.
        self.engine.on_progress(self._progress_q.put)
        # clear anything left over from a previous run so its final stats cannot flash on screen
        while not self._progress_q.empty():
            try:
                self._progress_q.get_nowait()
            except queue.Empty:
                break

        if dry:
            self.warn_label.configure(text=self.tr("s.dry_run"))
        else:
            self.warn_label.configure(text=self._warnings_for(profile))

        self.start_btn.configure(state="disabled")
        self.test_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_box.configure(text=self.tr("app.running"))

        # Order is load-bearing: the buttons must already show "running" before the polling loop starts,
        # because the loop decides at its first tick whether a run is in progress by looking at exactly
        # that state. Starting the engine first would give the loop a thread that may already have
        # finished, and it would immediately call _after_run on a run that just began.
        if self._poll_id:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        # Arm the force stop BEFORE the first click. If it were armed after, a run whose first repetition
        # is immediate would have a moment with no way to stop it.
        self._arm_force_stop(profile)
        self._drain_queue()
        self.engine.start(profile)

    def _warnings_for(self, p: Profile) -> str:
        """Warn about the two configurations that surprise people, without blocking either."""
        msgs = []
        if p.interval_ms == 0:
            msgs.append(self.tr("w.interval_zero"))
        if 0 < p.interval_ms < 10:
            msgs.append(self.tr("w.high_rate"))
        if p.repeat == 0 and p.max_duration_ms == 0:
            msgs.append(self.tr("w.unlimited"))
        return "  ".join(msgs)

    def _stop(self) -> None:
        if self.engine:
            self.engine.stop("stopped by user")
        self._after_run()

    def _arm_force_stop(self, profile: Profile) -> None:
        """
        Install the force stop hook for this run, and say so on screen.

        The key is shown next to the buttons because a force stop the user cannot remember is not a force
        stop. If the hook cannot be installed, that is stated plainly: silently having no emergency stop
        during a clicking run is worse than not offering one.
        """
        self.force_watcher._target_vk = _resolve_force_key(profile.force_stop_key or "enter")
        self.force_watcher._swallow = bool(profile.force_stop_swallow)
        ok = self.force_watcher.arm()
        if ok:
            self.force_label.configure(
                text=self.tr("f.force_stop_armed").format(key=(profile.force_stop_key or "enter").upper()),
                foreground="#0a7d28",
            )
        else:
            self.force_label.configure(
                text=f"{self.tr('f.force_stop')}: {self.force_watcher.error}",
                foreground="#b06000",
            )

    def _disarm_force_stop(self) -> None:
        """Remove the hook as soon as the run ends. No keyboard hook while idle."""
        self.force_watcher.disarm()
        self.force_label.configure(
            text=self.tr("f.force_stop_ready").format(
                key=(self.current.force_stop_key or "enter").upper()),
            foreground="#666",
        )

    def _force_stop_fired(self) -> None:
        """
        Runs on the keyboard-hook thread. Must not touch Tk.

        `Engine.stop()` only sets a threading.Event, which is safe from any thread and is the whole point:
        the stop takes effect immediately, inside the hook, without waiting for the interface to be free.
        Anything routed through the UI could be delayed by a busy event loop, and a force stop that
        depends on the interface being responsive is not a force stop.
        """
        if self.engine is not None:
            self.engine.stop("force stop key")

    def _hotkey_fired(self) -> None:
        """
        Runs on the hotkey thread, so it must not touch widgets. `after` is the only thread-safe way
        in to Tk, and it is also what makes the hotkey work while the app is unfocused.
        """
        self.root.after(0, self._toggle_from_hotkey)

    def _toggle_from_hotkey(self) -> None:
        if self.engine and self.engine.is_running():
            self._stop()
        else:
            self._start(False)

    def _drain_queue(self) -> None:
        """
        Consume progress reports on the Tk thread, and finish the run when the engine has stopped.

        Two jobs, and the second is the important one. Restoring the buttons used to depend on a final
        progress callback arriving after the engine thread had died, which never happened: the last
        callback is sent from inside the loop while the thread is still alive, so `is_running()` was
        still True and `_after_run` was declined. The result was an app usable exactly once per launch.

        Polling ends when the engine is no longer alive, which is a condition the UI can always observe
        for itself rather than waiting to be told.
        """
        drained = False
        while True:
            try:
                stats = self._progress_q.get_nowait()
            except queue.Empty:
                break
            self._last_stats = stats
            drained = True

        if drained:
            self._refresh_status(self._last_stats)

        engine = self.engine
        if engine is None:
            self._poll_id = None
            return

        # A run is over when its thread has died AND it has reported at least once. Checking only the
        # thread was wrong: `is_running()` is False for a moment after start() spawns the thread, so the
        # first poll declared the run finished, showed the pre-run zeroes and re-enabled the buttons.
        seen_progress = drained or self._last_stats.repeats_done > 0
        if not engine.is_running() and seen_progress:
            self._poll_id = None
            if str(self.stop_btn["state"]) == "normal":
                self._after_run()
            return

        self._poll_id = self.root.after(30, self._drain_queue)

    def _after_run(self) -> None:
        self._disarm_force_stop()
        self.start_btn.configure(state="normal")
        self.test_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_box.configure(text=self.tr("s.ready"))
        self._refresh_status()

    def _refresh_status(self, stats: RunStats | None = None) -> None:
        s = stats or (self.engine.stats if self.engine else self._last_stats)
        elapsed = max(0, s.finished_at_ms - s.started_at_ms)
        self.stat_labels["s.clicks"].configure(text=f"{s.clicks_sent:,}")
        self.stat_labels["s.repeats"].configure(text=f"{s.repeats_done:,}")
        self.stat_labels["s.keys"].configure(text=f"{s.keys_sent:,}")
        self.stat_labels["s.elapsed"].configure(text=f"{elapsed / 1000:.1f}s")
        self.stat_labels["s.missed"].configure(text=f"{s.missed_ticks:,}")
        self.stat_labels["s.late"].configure(text=f"{s.max_late_ms}ms")

        if s.error:
            self.warn_label.configure(text=f"{self.tr('s.error')}: {s.error}")
        # NB: the end-of-run state transition deliberately does NOT live here. It is driven by the
        # polling loop in `_drain_queue`, which can always see whether the engine is alive; making it
        # depend on a callback arriving at the right moment is what left Start disabled forever.

    # ------------------------------------------------------------------ misc

    def _capture(self) -> None:
        """Read the cursor position from the OS. Only meaningful on Windows."""
        try:
            from ..core.wininput import WindowsBackend

            backend = WindowsBackend()
            x, y = backend.cursor_pos()
            self.v_x.set(str(x))
            self.v_y.set(str(y))
            self.v_position.set("fixed")
        except Exception as e:  # noqa: BLE001 - report rather than crash
            self.warn_label.configure(text=f"{self.tr('f.capture')}: {e}")

    def _toggle_top(self) -> None:
        self.root.attributes("-topmost", bool(self.v_top.get()))
        self.settings["always_on_top"] = bool(self.v_top.get())
        store.save_settings(self.settings)

    def _set_language(self, lang: str) -> None:
        self.lang = lang if lang in strings.LANGUAGES else strings.DEFAULT_LANGUAGE
        self.settings["language"] = self.lang
        store.save_settings(self.settings)
        # applies now: a language is a preference, not a restart
        self._apply_language()

    def _register_hotkey(self) -> None:
        spec = self.current.hotkey or "f6"
        ok = self.hotkey.register(spec)
        if ok:
            self.hotkey_label.configure(text=f"{self.tr('f.hotkey')}: {spec}")
        else:
            # not fatal: the buttons still work, and the reason is shown
            self.hotkey_label.configure(text=f"{self.tr('f.hotkey')}: {spec} — {self.hotkey.error}")

    def _on_close(self) -> None:
        if self.engine and self.engine.is_running():
            if not messagebox.askyesno(self.tr("app.stop"), self.tr("w.verify")):
                return
            self.engine.stop("window closed")
        self.hotkey.unregister()
        self.force_watcher.close()
        self.root.destroy()

    def _update_hz(self) -> None:
        try:
            ms = int(self.v_interval.get())
        except ValueError:
            self.hz_label.configure(text="")
            return
        if ms <= 0:
            self.hz_label.configure(text="→ as fast as possible")
            return
        self.hz_label.configure(text=f"→ {1000 / ms:.1f}/s")

    @staticmethod
    def _int_or(text: str, default: int) -> int:
        try:
            return int((text or "").strip())
        except ValueError:
            return default


def _resolve_force_key(name: str) -> int:
    """Resolve a key name to a virtual-key code, falling back to Enter if it is unusable."""
    from ..core.wininput import key_to_vk

    try:
        return key_to_vk(name)
    except Exception:  # noqa: BLE001
        return key_to_vk("enter")


def main() -> int:
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.2)
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
    return 0
