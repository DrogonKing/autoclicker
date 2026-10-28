"""
Profile storage.

Two locations, chosen at runtime:

  - Portable build: a `profiles` folder next to the executable. A user who runs the tool from a USB
    stick expects the settings to travel with it, and writing to %APPDATA% would silently split their
    configuration in two.
  - Installed build: %APPDATA%/AutoClicker. An installed program must not try to write inside
    Program Files, which is read-only for a normal user.

Writes go through a temporary file and a replace, so an interrupted save cannot leave a half-written
profiles.json that loses every profile at once.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..core.errors import ProfileError
from ..core.model import Profile, from_dict, to_dict

APP_DIR_NAME = "AutoClicker"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def is_portable() -> bool:
    """
    Portable means: no marker file, but running frozen beside a writable folder.

    The installer writes a `.installed` marker next to the executable. Its presence is the single
    signal that decides storage location, so the two builds cannot disagree about where settings are.
    """
    if not is_frozen():
        return False
    exe_dir = Path(sys.executable).parent
    return not (exe_dir / ".installed").exists()


def data_dir() -> Path:
    """Where profiles and settings live."""
    if is_frozen():
        exe_dir = Path(sys.executable).parent
        if is_portable():
            return exe_dir / "profiles"
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or str(exe_dir)
        return Path(base) / APP_DIR_NAME
    # development: inside the repo, so tests and manual runs never touch a real user's data
    return Path(__file__).resolve().parents[3] / ".local"


def profiles_file() -> Path:
    return data_dir() / "profiles.json"


def settings_file() -> Path:
    return data_dir() / "settings.json"


def _atomic_write(path: Path, text: str) -> None:
    """
    Write via a temp file in the same directory, then replace.

    A direct write that fails halfway destroys the previous contents. Replacing is atomic on the same
    filesystem, so the old file survives any failure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_profiles(path: Path | None = None) -> list[Profile]:
    """
    Load every profile.

    A single unreadable entry does not discard the rest: losing nine good profiles because the tenth
    was hand-edited is not an acceptable failure mode.
    """
    p = path or profiles_file()
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    if isinstance(raw, dict):
        raw = raw.get("profiles", [])
    if not isinstance(raw, list):
        return []

    out: list[Profile] = []
    for item in raw:
        try:
            out.append(from_dict(item))
        except (ProfileError, ValueError, TypeError):
            continue
    return out


def save_profiles(profiles: list[Profile], path: Path | None = None) -> Path:
    p = path or profiles_file()
    payload: dict[str, Any] = {
        "version": 1,
        "profiles": [to_dict(x) for x in profiles],
    }
    _atomic_write(p, json.dumps(payload, ensure_ascii=False, indent=2))
    return p


def load_settings(path: Path | None = None) -> dict[str, Any]:
    p = path or settings_file()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(settings: dict[str, Any], path: Path | None = None) -> Path:
    p = path or settings_file()
    _atomic_write(p, json.dumps(settings, ensure_ascii=False, indent=2))
    return p


def storage_note() -> str:
    """A sentence for the About panel explaining where things are kept."""
    where = data_dir()
    kind = "portable" if is_portable() else ("installed" if is_frozen() else "development")
    return f"{kind}: {where}"
