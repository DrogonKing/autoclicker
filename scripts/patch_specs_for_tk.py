#!/usr/bin/env python3
"""
Add explicit Tk library bundling to both spec files.

Why this is needed at all, and why it was found by running the build rather than by reading about it:

    ImportError: libtcl9.0.so: cannot open shared object file

PyInstaller's Tk hook finds Tk when it is laid out the way CPython from python.org lays it out: a
`tcl/` directory beside the interpreter with `libtcl8.6.so` / `tcl86t.dll` in it. The interpreter on
the machine this was written on ships Tk 9 in a modular layout - `libtcl9.0.so` and a separate
`libtcl9tk9.0.so` under `lib/`, plus `tcl9.0/` - and the hook collects none of it.

The fix is to locate Tk's libraries and init script ourselves and hand them to PyInstaller. On
Windows the same code collects `tcl86t.dll`, `tk86t.dll` and the `tcl8.6`/`tk8.6` script folders, so
one implementation covers both and CI exercises the Windows path.
"""
import pathlib
import re

SPECS = [
    pathlib.Path("/root/autoclicker/autoclick-portable.spec"),
    pathlib.Path("/root/autoclicker/autoclick-dir.spec"),
]

TK_HELPER = '''
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
    # de-duplicate by final component: the same library can be reachable by two paths
    seen = set()
    out = []
    for f in found:
        name = os.path.basename(f)
        if name in seen:
            continue
        seen.add(name)
        out.append(f)
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
                out.append((p, name))
    return out


_tk_bin = _tk_binaries()
_tk_data = _tk_datas()
print(f"[spec] Tk libraries collected: {len(_tk_bin)}")
for _b in _tk_bin:
    print(f"[spec]   lib  {os.path.basename(_b)}")
print(f"[spec] Tk script dirs collected: {len(_tk_data)}")
for _d, _name in _tk_data:
    print(f"[spec]   dir  {_name}")

# --- build --------------------------------------------------------------------------------------
'''

for spec in SPECS:
    text = spec.read_text()
    if "_tk_binaries" in text:
        print(f"{spec.name}: already patched")
        continue

    # insert the helper just before the Analysis call, and add `import os` at the top
    text = text.replace("import sys\n", "import sys\n", 1)
    marker = "analysis = Analysis("
    if marker not in text:
        print(f"{spec.name}: analysis marker not found")
        continue
    text = text.replace(marker, TK_HELPER + marker, 1)

    # feed the collected files into Analysis
    text = text.replace(
        "    binaries=[],\n    datas=[],",
        "    binaries=_tk_bin,\n    datas=_tk_data,",
        1,
    )
    if "_tk_bin," not in text:
        print(f"{spec.name}: FAILED to inject binaries/datas")
        continue
    spec.write_text(text)
    print(f"{spec.name}: patched")

print()
for spec in SPECS:
    t = spec.read_text()
    print(f"{spec.name}: binaries={'binaries=_tk_bin' in t} datas={'datas=_tk_data' in t} helper={'_tk_binaries' in t}")
