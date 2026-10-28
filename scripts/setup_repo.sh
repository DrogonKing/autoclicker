#!/usr/bin/env bash
# Create the repository if needed and push. The token comes from the environment, never as an
# argument, and every output line is scrubbed before printing.
set -uo pipefail

if [ -z "${GH_TOKEN_PUSH:-}" ]; then echo "no token supplied"; exit 1; fi

REPO="autoclicker"
API="https://api.github.com"

echo "=== 1. who is this token? ==="
curl -s -H "Authorization: Bearer $GH_TOKEN_PUSH" "$API/user" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('  user:', d.get('login'), '| scopes are checked next')"

echo "=== 2. does the repo already exist? ==="
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $GH_TOKEN_PUSH" "$API/repos/DrogonKing/$REPO")
if [ "$STATUS" = "200" ]; then
  echo "  exists"
else
  echo "  not found (HTTP $STATUS) - creating"
  curl -s -X POST -H "Authorization: Bearer $GH_TOKEN_PUSH" \
    -H "Accept: application/vnd.github+json" \
    "$API/user/repos" \
    -d "{\"name\":\"$REPO\",\"description\":\"Customizable autoclicker for Windows: scheduled start, exact repeat counts, simultaneous clicks and key chords with millisecond gaps. Portable and installed builds.\",\"private\":false,\"has_issues\":true,\"has_wiki\":false}" \
    | python3 -c "
import json,sys
d=json.load(sys.stdin)
if d.get('full_name'):
    print('  created:', d['full_name'])
else:
    print('  FAILED:', d.get('message'), d.get('errors'))
"
fi

echo "=== 3. token scopes (needs 'repo' and 'workflow' for the Actions file) ==="
curl -sI -H "Authorization: Bearer $GH_TOKEN_PUSH" "$API/user" \
  | grep -i '^x-oauth-scopes:' | sed 's/^/  /' || echo "  (fine-grained token: scopes are per-repository)"
