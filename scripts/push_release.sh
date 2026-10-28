#!/usr/bin/env bash
# Push main and the v1.0.0 tag, which starts the Windows build.
set -uo pipefail
cd /root/autoclicker

if [ -z "${GH_TOKEN_PUSH:-}" ]; then echo "no token"; exit 1; fi

git branch -M main 2>/dev/null || true
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/DrogonKing/autoclicker.git"

export GIT_ASKPASS=/bin/true
HELPER='!f() { echo username=DrogonKing; echo "password=$GH_TOKEN_PUSH"; }; f'

echo "=== push main ==="
git -c credential.helper="$HELPER" push -u origin main 2>&1 | sed -E 's/gh[pousr]_[A-Za-z0-9]+/[REDACTED]/g'

echo "=== tag v1.0.0 ==="
git tag -d v1.0.0 >/dev/null 2>&1 || true
git tag -a v1.0.0 -m "1.0.0: interval, exact counts, scheduled start, simultaneous clicks, key chords with gaps, sequences, global hotkey, test mode, EN/FA"
git -c credential.helper="$HELPER" push -f origin v1.0.0 2>&1 | sed -E 's/gh[pousr]_[A-Za-z0-9]+/[REDACTED]/g'

echo "=== state ==="
git log --oneline -1 | cat
git tag -l
echo "remote: $(git remote get-url origin)"
