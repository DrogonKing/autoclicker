# Shared PyInstaller settings for both build modes.
#
# Two spec files exist rather than one with a flag because PyInstaller rejects --onefile when a .spec
# is given: "makespec options not valid when a .spec file is given". The build mode is therefore a
# property of the file, and the two graphs are genuinely different anyway (see each file).

import sys

# tkinter is imported lazily inside the UI module, so static analysis can miss it. A missing tkinter
# produces an executable that starts and immediately exits with no window - the worst failure to
# diagnose from a user report.
HIDDEN = [
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
    "tkinter.filedialog",
    "tkinter.font",
]

# Nothing in this program uses these. Excluding them keeps the portable build small.
EXCLUDES = [
    "numpy", "pandas", "matplotlib", "PIL", "scipy", "pytest", "setuptools", "pip",
]


# --- Tk libraries -------------------------------------------------------------------------------
#
# Collected explicitly rather than trusted to PyInstaller's hook. The hook assumes the python.org
# layout (`tcl/` beside the interpreter, `libtcl8.6.so` / `tcl86t.dll`); this host's CPython ships Tk 9
# modular (`libtcl9.0.so`, `libtcl9tk9.0.so`, `tcl9.0/`), and the hook silently collects none of it.
# The result is an executable that builds cleanly and dies with
# "ImportError: libtcl9.0.so: cannot open shared object file" - found by running it.
def _tk_binaries():
    import glob
    import os
    import sysconfig

    found = []
    libdirs = [
        sysconfig.get_config_var("LIBDIR"),
        sysconfig.get_paths().get("platstdlib"),
        os.path.join(sysconfig.get_paths().get("stdlib", ""), "lib-dynload"),
    ]
    patterns = [
        "libtcl*.so*", "libtk*.so*", "libtcl*.dylib", "libtk*.dylib",
        "tcl*.dll", "tk*.dll", "zlib1.dll",
    ]
    for d in libdirs:
        if not d or not os.path.isdir(d):
            continue
        for pat in patterns:
            for hit in glob.glob(os.path.join(d, pat)):
                if os.path.isfile(hit) and not os.path.islink(hit):
                    found.append(hit)
    # de-duplicate by final component: the same library can be reachable by two paths.
    # The return shape is (source, destination_dir) pairs, which is what PyInstaller's Analysis
    # expects - a list of bare paths fails with "too many values to unpack (expected 2)".
    seen = set()
    out = []
    for f in found:
        name = os.path.basename(f)
        if name in seen:
            continue
        seen.add(name)
        out.append((f, "."))
    return out


def _tk_datas():
    """The Tcl script directories, which Tk needs at run time to create any widget at all."""
    import os
    import sysconfig

    roots = {
        sysconfig.get_config_var("LIBDIR") or "",
        os.path.dirname(os.path.dirname(sysconfig.get_paths().get("stdlib", ""))),
    }
    out = []
    for root in sorted(r for r in roots if r and os.path.isdir(r)):
        for name in os.listdir(root):
            p = os.path.join(root, name)
            if not os.path.isdir(p):
                continue
            # tcl8.6, tk8.6, tcl9.0, tcl9, tk9, tcl9tk9.0 ...
            low = name.lower()
            if low.startswith("tcl") or low.startswith("tk"):
                # destination is the script directory's own name, so Tk finds it where it expects
                out.append((p, name))
    return out


_tk_bin = _tk_binaries()
_tk_data = _tk_datas()
print(f"[spec] Tk libraries collected: {len(_tk_bin)}")
for _src, _dst in _tk_bin:
    print(f"[spec]   lib  {os.path.basename(_src)}")
print(f"[spec] Tk script dirs collected: {len(_tk_data)}")
for _d, _name in _tk_data:
    print(f"[spec]   dir  {_name}")


# --- build --------------------------------------------------------------------------------------
pyz = PYZ(analysis.pure)

# The installer packages this tree. The executable references the collected files instead of
# containing them, so it starts faster and the installer compresses the whole directory.
#
# COLLECT receives the binaries and data, NOT the exe: passing the exe as well fails with
# "Resource ... is not a valid file", and an EXE with exclude_binaries=False in a one-dir build is
# the same mistake in a different place.
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="AutoClicker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="AutoClicker",
)
