"""
The core: everything platform-independent.

No module in here may import tkinter, ctypes, or anything Windows-specific except `wininput`, which
guards its own platform access so that importing it on Linux still works and the tests can run
anywhere. Keeping that rule is what makes the timing testable.
"""
