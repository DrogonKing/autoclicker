"""
Errors shared by the core.

In its own module because both `model` and `schedule` raise it and both are imported by `engine`:
putting it in any one of them creates an import cycle, which is the kind of thing that works until
the import order changes.
"""

from __future__ import annotations


class ProfileError(ValueError):
    """A profile that cannot be run. The message is written for a person, not a log."""


class ParseError(ValueError):
    """Something the user typed that could not be understood."""
