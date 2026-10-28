# PyInstaller build: the directory tree the installer packages.
#
# A separate file from autoclick-portable.spec because PyInstaller rejects --onefile when a .spec is given
# ("makespec options not valid when a .spec file is given"), so the mode is a property of the file.
#
# Every setting above the build section is identical to autoclick-portable.spec by construction: this
# file was generated from it. If you change one, change the other, or the installer and portable builds
# would behave differently - the kind of difference nobody thinks to test.

import glob
import os
import sys
import sysconfig

# tkinter is imported lazily inside the UI module, so static analysis can miss it. A missing tkinter
# produces an executable that starts and immediately dies with no window - the worst failure to
# diagnose from a user report.
HIDDEN = [
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
    "tkinter.filedialog",
    "tkinter.font",
    "tkinter.constants",
]

# Nothing in this program uses these. Excluding them keeps the portable build small.
EXCLUDES = [
    "numpy", "pandas", "matplotlib", "PIL", "scipy", "pytest", "setuptools", "pip",
]


def _tk_binaries():
    """
    Find Tk's shared libraries.

    Explicit rather than trusted to PyInstaller's hook. The hook expects the python.org layout (a
    `tcl/` directory beside the interpreter with `libtcl8.6.so` or `tcl86t.dll`). The CPython used to
    develop this ships Tk 9 modular - `libtcl9.0.so` plus a separate `libtcl9tk9.0.so` under `lib/` -
    and the hook collected NONE of it, which produced a build that died with
    "ImportError: libtcl9.0.so: cannot open shared object file".

    On Windows the same code collects tcl86t.dll, tk86t.dll and their script folders, so one
    implementation covers both platforms and CI exercises the Windows path.

    The return shape is (source, destination_directory) pairs, which is what Analysis expects - a list
    of bare paths fails with "too many values to unpack (expected 2)".
    """
    found = []
    bases = []
    for key in ("LIBDIR", "purelib", "platlib"):
        v = sysconfig.get_config_var(key) or sysconfig.get_paths().get(key)
        if v:
            bases.append(v)
    bases.append(sysconfig.get_paths().get("stdlib", ""))
    bases.append(os.path.join(sysconfig.get_paths().get("stdlib", ""), "lib-dynload"))
    # the python.org Windows layout keeps Tk beside the interpreter
    bases.append(os.path.dirname(sys.executable))
    bases.append(os.path.join(os.path.dirname(sys.executable), "DLLs"))
    bases.append(os.path.join(os.path.dirname(sys.executable), "tcl"))

    patterns = [
        "libtcl*.so*", "libtk*.so*", "libtcl*.dylib", "libtk*.dylib",
        "tcl*.dll", "tk*.dll", "_tkinter*.pyd", "zlib1.dll",
    ]
    for base in bases:
        if not base or not os.path.isdir(base):
            continue
        for pat in patterns:
            for hit in glob.glob(os.path.join(base, pat)):
                if os.path.isfile(hit):
                    found.append(hit)
    # de-duplicate by file name: the same library is reachable by several paths
    seen = set()
    out = []
    for f in sorted(found):
        name = os.path.basename(f)
        if name in seen:
            continue
        seen.add(name)
        out.append((f, "."))
    return out


def _tk_datas():
    """
    Find Tk's script directories.

    Without these Tk cannot create a single widget: `init.tcl` lives in them. Destination is the
    directory's own name, so Tk finds it where it looks for it.
    """
    roots = set()
    for key in ("LIBDIR", "purelib", "platlib"):
        v = sysconfig.get_config_var(key) or sysconfig.get_paths().get(key)
        if v:
            roots.add(os.path.dirname(v.rstrip("/\\")))
            roots.add(v)
    roots.add(os.path.dirname(sys.executable))
    roots.add(os.path.join(os.path.dirname(sys.executable), "tcl"))

    out = []
    for root in sorted(r for r in roots if r and os.path.isdir(r)):
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name)
            if not os.path.isdir(p):
                continue
            low = name.lower()
            # tcl8.6, tk8.6, tcl9.0, tcl9, tk9, tcl9tk9.0, tcl, tk
            if low in ("tcl", "tk") or low.startswith("tcl") or low.startswith("tk"):
                out.append((p, name))
    # de-duplicate by destination name: two roots can offer the same directory
    seen = set()
    final = []
    for src, dst in out:
        if dst in seen:
            continue
        seen.add(dst)
        final.append((src, dst))
    return final


_tk_bin = _tk_binaries()
_tk_data = _tk_datas()

print(f"[spec] Tk libraries collected: {len(_tk_bin)}")
for _src, _dst in _tk_bin:
    print(f"[spec]   lib  {os.path.basename(_src)}")
print(f"[spec] Tk script dirs collected: {len(_tk_data)}")
for _src, _dst in _tk_data:
    print(f"[spec]   dir  {_dst}")

# A Windows build with no Tk libraries is broken and must fail here, not on a user's machine. The
# earlier CI run printed "Tk libraries collected: 0" and carried on to a build that could not start.
if not _tk_bin or not _tk_data:
    raise SystemExit(
        f"Tk was not found (libraries: {len(_tk_bin)}, script dirs: {len(_tk_data)}). "
        f"An executable built without it cannot open a window."
    )

analysis = Analysis(
    ["src/autoclick/__main__.py"],
    pathex=["src"],
    binaries=_tk_bin,
    datas=_tk_data,
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(analysis.pure)

# The installer packages this tree. The executable references the collected files instead of containing
# them, so it starts faster and the installer compresses the whole directory.
#
# COLLECT receives the binaries and data, NOT the exe: passing the exe as well fails with
# "Resource ... is not a valid file", and exclude_binaries=False in a one-dir build is the same
# mistake in a different place.
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
