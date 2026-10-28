#!/usr/bin/env python3
"""
Keep exactly one release: the newest.

Four releases accumulated during this session because each CI fix needed its own tag. A user landing on
the releases page should see one download, not four near-identical ones where the older three contain
the bugs that were just fixed. That is not tidiness, it is the difference between the user getting the
working build and getting a broken one.

Deletes older releases and their tags, keeping the newest.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

TOKEN = os.environ.get("GH_TOKEN_PUSH", "")
REPO = "DrogonKing/autoclicker"
SCRUB = re.compile(r"gh[pousr]_[A-Za-z0-9]+")
KEEP = 1  # keep the newest N


def call(method: str, path: str):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "prune-releases",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        return json.loads(body) if body else None


if not TOKEN:
    raise SystemExit("no token")

rels = call("GET", f"/repos/{REPO}/releases")
# newest first by creation time
rels.sort(key=lambda r: r["created_at"], reverse=True)
print(f"{len(rels)} releases; keeping the newest {KEEP}\n")

for r in rels[KEEP:]:
    print(f"deleting release {r['tag_name']} ({len(r['assets'])} assets)")
    call("DELETE", f"/repos/{REPO}/releases/{r['id']}")
    # the tag survives a release deletion, so remove it too
    try:
        call("DELETE", f"/repos/{REPO}/git/refs/tags/{r['tag_name']}")
        print(f"  tag {r['tag_name']} deleted")
    except Exception as e:  # noqa: BLE001
        print(f"  tag {r['tag_name']} left behind ({e}); the release is gone either way")

print("\n=== releases now ===")
for r in call("GET", f"/repos/{REPO}/releases"):
    print(f"{r['tag_name']}")
    for a in r["assets"]:
        print(f"  {a['name']:34} {a['size'] / 1024 / 1024:6.1f} MB")
        print(f"    {a['browser_download_url']}")

print("\n=== tags now ===")
refs = call("GET", f"/repos/{REPO}/git/refs/tags")
for ref in refs or []:
    print(" ", ref["ref"].replace("refs/tags/", ""))