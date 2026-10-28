#!/usr/bin/env python3
"""
Watch the build and report failures with their actual log text.

Polling rather than trusting: a workflow that starts is not a workflow that passes, and this CI runs
the two checks that cannot run anywhere else (the SendInput structure layout, and the packaged
binary's own self test). Reporting "pushed" without those would be reporting nothing.

On failure it fetches the failing job's log tail, because "job failed" without the reason costs
another round trip.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request

TOKEN = os.environ.get("GH_TOKEN_PUSH", "")
REPO = "DrogonKing/autoclicker"
API = "https://api.github.com"
SCRUB = re.compile(r"gh[pousr]_[A-Za-z0-9]+")

if not TOKEN:
    print("no token supplied")
    sys.exit(1)


def api(path: str, raw: bool = False):
    req = urllib.request.Request(
        f"{API}{path}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
            "User-Agent": "autoclicker-ci-watch",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
    return body.decode("utf-8", "replace") if raw else json.loads(body)


def log_tail(job_id: int, lines: int = 60) -> str:
    try:
        text = api(f"/repos/{REPO}/actions/jobs/{job_id}/logs", raw=True)
    except Exception as e:  # noqa: BLE001
        return f"  (could not fetch the log: {e})"
    tail = text.strip().splitlines()[-lines:]
    return SCRUB.sub("[REDACTED]", "\n".join("  " + line for line in tail))


def main() -> int:
    print("waiting for the workflow to be registered...")
    run = None
    for _ in range(30):
        time.sleep(10)
        runs = api(f"/repos/{REPO}/actions/runs?per_page=5")["workflow_runs"]
        if runs:
            run = runs[0]
            break
    if run is None:
        print("no workflow run appeared; check that the workflow file is on the default branch")
        return 1

    run_id = run["id"]
    print(f"run {run_id}: {run['name']} ({run['event']} on {run['head_branch']})")
    print(f"https://github.com/{REPO}/actions/runs/{run_id}")

    last = ""
    for _ in range(90):
        r = api(f"/repos/{REPO}/actions/runs/{run_id}")
        status, conclusion = r["status"], r["conclusion"]
        line = f"{status}/{conclusion or '-'}"
        if line != last:
            print(f"  {line}")
            last = line
        if status == "completed":
            break
        time.sleep(20)

    r = api(f"/repos/{REPO}/actions/runs/{run_id}")
    print()
    print(f"=== final: {r['status']} / {r['conclusion']} ===")

    jobs = api(f"/repos/{REPO}/actions/runs/{run_id}/jobs")["jobs"]
    for job in jobs:
        print(f"  {job['name']:28} {job['status']:12} {job['conclusion'] or '-'}")

    if r["conclusion"] != "success":
        print()
        print("=== failing steps ===")
        for job in jobs:
            if job["conclusion"] in ("failure", "cancelled"):
                for step in job.get("steps", []):
                    if step.get("conclusion") == "failure":
                        print(f"  {job['name']} -> {step['name']}")
                print(log_tail(job["id"]))
        return 1

    print()
    print("=== release assets ===")
    try:
        rel = api(f"/repos/{REPO}/releases/tags/v1.0.0")
        for a in rel.get("assets", []):
            print(f"  {a['name']:44} {a['size'] / 1024 / 1024:6.1f} MB")
            print(f"    {a['browser_download_url']}")
    except Exception as e:  # noqa: BLE001
        print(f"  (release not readable yet: {e})")
        print(f"  check https://github.com/{REPO}/releases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
