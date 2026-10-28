#!/usr/bin/env python3
"""
Fetch a job's log.

GitHub's log endpoint answers with a 302 to a signed URL on a different host, and sending the
Authorization header to that host produces "Server failed to authenticate". So the redirect is
followed manually and the token is dropped for it - a detail that costs one round trip if you have to
discover it by trial.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

TOKEN = os.environ.get("GH_TOKEN_PUSH", "")
REPO = "DrogonKing/autoclicker"
API = "https://api.github.com"
SCRUB = re.compile(r"gh[pousr]_[A-Za-z0-9]+")

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def get(url: str, token: bool = True, follow: bool = True):
    req = urllib.request.Request(url, headers={"User-Agent": "ci-log-fetch"})
    if token:
        req.add_header("Authorization", f"Bearer {TOKEN}")
        req.add_header("Accept", "application/vnd.github+json")
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    return opener.open(req, timeout=60)


def main() -> int:
    if not TOKEN:
        print("no token")
        return 1

    runs = json.load(get(f"{API}/repos/{REPO}/actions/runs?per_page=5"))["workflow_runs"]
    run = next((r for r in runs if RUN_ID is None or str(r["id"]) == str(RUN_ID)), runs[0])
    print(f"run {run['id']}  {run['head_branch']}  {run['status']}/{run['conclusion']}")
    print(f"https://github.com/{REPO}/actions/runs/{run['id']}")
    print()

    jobs = json.load(get(f"{API}/repos/{REPO}/actions/runs/{run['id']}/jobs"))["jobs"]
    for job in jobs:
        print(f"=== {job['name']}  ({job['conclusion']}) ===")
        for step in job.get("steps", []):
            mark = "FAIL" if step.get("conclusion") == "failure" else "    "
            print(f"  {mark} {step['number']:2}. {step['name']}")

        if job["conclusion"] not in ("failure", "cancelled"):
            continue

        print()
        print(f"--- log for {job['name']} ---")
        try:
            resp = get(f"{API}/repos/{REPO}/actions/jobs/{job['id']}/logs", follow=False)
            location = resp.headers.get("Location")
            if not location:
                print("  no redirect; the log may need a different permission")
                continue
            # the signed URL rejects the Authorization header, so it is not sent
            with get(location, token=False) as log:
                text = log.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            print(f"  could not fetch: {e}")
            continue

        lines = text.splitlines()
        # print around the failure, not just the tail: the useful part is the traceback, and the tail
        # is usually the "process completed with exit code" line
        interesting = [
            i for i, line in enumerate(lines)
            if any(k in line for k in ("FAILED", "Error", "error:", "assert", "Traceback", "E   "))
        ]
        shown: set[int] = set()
        for idx in interesting[-6:]:
            lo, hi = max(0, idx - 12), min(len(lines), idx + 6)
            for j in range(lo, hi):
                if j not in shown:
                    print("  " + SCRUB.sub("[REDACTED]", lines[j]))
                    shown.add(j)
            print("  ...")
        if not interesting:
            for line in lines[-40:]:
                print("  " + SCRUB.sub("[REDACTED]", line))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
