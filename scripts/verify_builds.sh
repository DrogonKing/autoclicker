#!/usr/bin/env bash
# Rebuild both PyInstaller modes locally and run each binary's selftest.
set -uo pipefail
cd /root/autoclicker

echo "=== specs ==="
for f in autoclick-portable.spec autoclick-dir.spec; do
  echo "$f: analysis=$(grep -c '^analysis = Analysis' "$f") tklibs=$(grep -c '_tk_binaries()' "$f") guard=$(grep -c 'cannot open a window' "$f")"
done

echo
echo "=== portable build ==="
rm -rf /tmp/fp /tmp/fpb
.venv/bin/pyinstaller autoclick-portable.spec --noconfirm --distpath /tmp/fp --workpath /tmp/fpb > /tmp/fp.log 2>&1
echo "exit=$?"
grep -E '\[spec\]|Build complete|SystemExit|not found' /tmp/fp.log | head -12
ls -la /tmp/fp/ 2>/dev/null

echo
echo "=== dir build ==="
rm -rf /tmp/fd /tmp/fdb
.venv/bin/pyinstaller autoclick-dir.spec --noconfirm --distpath /tmp/fd --workpath /tmp/fdb > /tmp/fd.log 2>&1
echo "exit=$?"
grep -E 'Build complete|SystemExit|not found' /tmp/fd.log | head -6
ls /tmp/fd/AutoClicker/ 2>/dev/null

echo
echo "=== both binaries run their selftest ==="
for exe in /tmp/fp/AutoClicker /tmp/fd/AutoClicker/AutoClicker; do
  if [ -x "$exe" ]; then
    echo "--- $exe ---"
    timeout 90 xvfb-run -a --server-args="-screen 0 1024x768x24" "$exe" --selftest 2>&1 | tail -4
  fi
done
