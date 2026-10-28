#!/usr/bin/env python3
"""List the assets of every release, so the download links can be handed over."""
import json
import os
import re
import urllib.request

TOKEN = os.environ.get("GH_TOKEN_PUSH", "")
REPO = "DrogonKing/autoclicker"
SCRUB = re.compile(r"gh[pousr]_[A-Za-z0-9]+")


def api(path: str):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
                 "User-Agent": "release-list"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


rels = api(f"/repos/{REPO}/releases")
if not rels:
    print("no releases yet")
    raise SystemExit(1)

for rel in rels:
    assets = rel.get("assets", [])
    if not assets:
        continue
    print(f"{rel['tag_name']}  ({rel['published_at'][:10]})")
    for a in assets:
        # a release is only useful if the files are actually attached
        print(f"  {a['name']:42} {a['size'] / 1024 / 1024:7.1f} MB   {a['download_count']} downloads")
        print(f"    {a['browser_download_url']}")
    print()
