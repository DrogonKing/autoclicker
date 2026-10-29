"""
Text, in both languages.

Centralised because the same word must mean the same thing in a label, an error and a log line. It is
also the file a translator can work on without reading any code.

Persian is written the way it is actually read: "۳ بار" not "3 بار", and the digits in *values* stay
Latin because a user comparing "۵۰۰ میلی‌ثانیه" against a settings file needs the number they can
copy. Labels are Persian, numbers are Latin.
"""

from __future__ import annotations

from typing import Any

LANGUAGES = ("en", "fa")
DEFAULT_LANGUAGE = "en"

# fa is RTL; the UI mirrors itself for it
RTL_LANGUAGES = ("fa",)

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # app
        "app.title": "AutoClicker",
        "app.subtitle": "Scheduled, counted, precise clicking",
        "app.start": "Start",
        "app.stop": "Stop",
        "app.test": "Test (no clicks)",
        "app.running": "Running",
        "app.language": "Language",
        "app.simple": "Simple",
        "app.advanced": "Advanced",
        "app.always_on_top": "Always on top",
        # fields
        "f.interval": "Interval",
        "f.count": "Repeat count",
        "f.count_hint": "0 = unlimited",
        "f.start": "Start at",
        "f.start_hint": "HH:MM:SS, or 2s / +1500 for a delay",
        "f.button": "Mouse button",
        "f.position": "Click where",
        "f.at_once": "Clicks at once",
        "f.at_once_hint": "same instant, no gap",
        "f.double": "Double click each time",
        "f.max_duration": "Stop after",
        "f.max_duration_hint": "0 = never; a safety net",
        "f.force_stop": "Force stop key",
        "f.force_stop_swallow": "hold it back while running",
        "f.force_stop_ready": "Force stop: press {key} during a run",
        "f.force_stop_armed": "Force stop ARMED: press {key} to stop now",
        "f.hotkey": "Start/stop hotkey",
        "f.add_click": "Add click",
        "f.add_key": "Add keys",
        "f.add_wait": "Add wait",
        "f.move_up": "Up",
        "f.move_down": "Down",
        "f.remove": "Remove",
        "f.gap": "Gap between keys",
        "f.keys": "Keys",
        "f.wait_ms": "Wait (ms)",
        "f.capture": "Capture cursor",
        # units
        "u.ms": "ms",
        "u.seconds": "s",
        "u.minutes": "min",
        "u.never": "never",
        "u.unlimited": "unlimited",
        # profiles
        "p.title": "Profiles",
        "p.save": "Save",
        "p.load": "Load",
        "p.delete": "Delete",
        "p.duplicate": "Duplicate",
        "p.name": "Name",
        # status
        "s.clicks": "Clicks",
        "s.repeats": "Repeats",
        "s.keys": "Keys",
        "s.missed": "Late ticks",
        "s.late": "Worst lateness",
        "s.elapsed": "Elapsed",
        "s.ready": "Ready",
        "s.dry_run": "Test mode: nothing will be clicked",
        "s.error": "Error",
        # warnings
        "w.interval_zero": "0 ms means as fast as this machine can go, with no waiting.",
        "w.high_rate": "Very high rate: the system timer may not keep up, and ticks will be reported as late.",
        "w.unlimited": "Unlimited repeats: set a stop-after time, or remember to press Stop.",
        "w.verify": "Confirm the target window is focused before starting.",
        # errors
        "e.interval": "Interval must be a whole number of milliseconds.",
        "e.count": "Repeat count must be 0 or more.",
        "e.start": "Start time must look like 11:50:20, or a delay like 2s.",
        "e.keys": "Enter at least one key, separated by spaces.",
        "e.gap": "Gap must be 0-60000 ms.",
        "e.at_once": "Clicks at once must be 1-100.",
        "e.no_steps": "Advanced mode needs at least one step.",
        "e.save_failed": "Could not save the profile.",
        "e.load_failed": "Could not load the profile.",
        # about
        "a.about": "About",
        "a.version": "Version",
        "a.portable": "Portable build: settings live next to the program",
        "a.tested": "Timing engine tested",
        "a.not_tested": "Input delivery can only be verified on Windows",
    },
    "fa": {
        "app.title": "کلیک‌کن خودکار",
        "app.subtitle": "کلیک زمان‌بندی‌شده، شمارش‌شده و دقیق",
        "app.start": "شروع",
        "app.stop": "توقف",
        "app.test": "آزمون (بدون کلیک)",
        "app.running": "در حال اجرا",
        "app.language": "زبان",
        "app.simple": "ساده",
        "app.advanced": "پیشرفته",
        "app.always_on_top": "همیشه رو",
        "f.interval": "فاصله",
        "f.count": "تعداد تکرار",
        "f.count_hint": "۰ یعنی بی‌نهایت",
        "f.start": "شروع در ساعت",
        "f.start_hint": "مثل 11:50:20 یا برای تأخیر 2s / +1500",
        "f.button": "دکمهٔ ماوس",
        "f.position": "کجا کلیک شود",
        "f.at_once": "کلیک همزمان",
        "f.at_once_hint": "در یک لحظه، بدون فاصله",
        "f.double": "هر بار دوبار کلیک",
        "f.max_duration": "توقف پس از",
        "f.max_duration_hint": "۰ یعنی هرگز؛ تور ایمنی",
        "f.force_stop": "کلید توقف اضطراری",
        "f.force_stop_swallow": "در حال اجرا کلید نگه داشته شود",
        "f.force_stop_ready": "توقف اضطراری: در حال اجرا {key} را بزن",
        "f.force_stop_armed": "توقف اضطراری فعال: برای توقف {key} را بزن",
        "f.hotkey": "کلید میان‌بر شروع/توقف",
        "f.add_click": "افزودن کلیک",
        "f.add_key": "افزودن کلید",
        "f.add_wait": "افزودن انتظار",
        "f.move_up": "بالا",
        "f.move_down": "پایین",
        "f.remove": "حذف",
        "f.gap": "فاصله بین کلیدها",
        "f.keys": "کلیدها",
        "f.wait_ms": "انتظار (ms)",
        "f.capture": "گرفتن موقعیت نشانگر",
        "u.ms": "میلی‌ثانیه",
        "u.seconds": "ثانیه",
        "u.minutes": "دقیقه",
        "u.never": "هرگز",
        "u.unlimited": "بی‌نهایت",
        "p.title": "پروفایل‌ها",
        "p.save": "ذخیره",
        "p.load": "بارگذاری",
        "p.delete": "حذف",
        "p.duplicate": "کپی",
        "p.name": "نام",
        "s.clicks": "کلیک‌ها",
        "s.repeats": "تکرارها",
        "s.keys": "کلیدها",
        "s.missed": "دیرکرد",
        "s.late": "بیشترین تأخیر",
        "s.elapsed": "زمان سپری‌شده",
        "s.ready": "آماده",
        "s.dry_run": "حالت آزمون: هیچ کلیکی انجام نمی‌شود",
        "s.error": "خطا",
        "w.interval_zero": "۰ میلی‌ثانیه یعنی بدون انتظار، به سرعت سخت‌افزار.",
        "w.high_rate": "نرخ بسیار بالا: تایمر سیستم ممکن است عقب بماند و دیرکرد گزارش شود.",
        "w.unlimited": "تکرار بی‌نهایت: زمان توقف بگذار، یا یادت باشد Stop را بزنی.",
        "w.verify": "قبل از شروع مطمئن شو پنجرهٔ هدف فعال است.",
        "e.interval": "فاصله باید عدد صحیح میلی‌ثانیه باشد.",
        "e.count": "تعداد تکرار باید ۰ یا بیشتر باشد.",
        "e.start": "زمان شروع باید مثل 11:50:20 یا تأخیر مثل 2s باشد.",
        "e.keys": "حداقل یک کلید بنویس، با فاصله جدا کن.",
        "e.gap": "فاصله باید بین ۰ تا ۶۰۰۰۰ میلی‌ثانیه باشد.",
        "e.at_once": "کلیک همزمان باید بین ۱ تا ۱۰۰ باشد.",
        "e.no_steps": "حالت پیشرفته حداقل یک گام لازم دارد.",
        "e.save_failed": "ذخیرهٔ پروفایل نشد.",
        "e.load_failed": "بارگذاری پروفایل نشد.",
        "a.about": "درباره",
        "a.version": "نسخه",
        "a.portable": "نسخهٔ پرتابل: تنظیمات کنار خود برنامه ذخیره می‌شود",
        "a.tested": "موتور زمان‌بندی تست‌شده",
        "a.not_tested": "ارسال ورودی فقط روی ویندوز قابل تأیید است",
    },
}


def t(key: str, lang: str = DEFAULT_LANGUAGE, **fmt: Any) -> str:
    """
    Look up a string.

    Falls back to English and then to the key itself rather than returning an empty label: a visible
    key name is a bug report, an empty label is a mystery.
    """
    table = STRINGS.get(lang) or STRINGS[DEFAULT_LANGUAGE]
    text = table.get(key)
    if text is None:
        text = STRINGS[DEFAULT_LANGUAGE].get(key, key)
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError):
            return text
    return text


def is_rtl(lang: str) -> bool:
    return lang in RTL_LANGUAGES
