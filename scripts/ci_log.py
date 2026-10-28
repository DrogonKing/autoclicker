#!/usr/bin/env python3
"""
Fetch a job's log, following the redirect without the Authorization header.

GitHub's job-log endpoint 302s to a signed blob URL on another host, and sending the Bearer token to
that host returns 401 "Server failed to authenticate". So the redirect is resolved first and the token
is dropped for the second request.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

TOKEN = os.environ.get("GH_TOKEN_PUSH", "")
REPO = os.environ.get("REPO", "DrogonKing/autoclicker")
API = "https://api.github.com"
SCRUB = re.compile(r"gh[pousr]_[A-Za-z0-9]+")

WANT_JOB = sys.argv[1] if len(sys.argv) > 1 else "package"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def open_(url: str, token: bool) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ci-log"})
    if token:
        req.add_header("Authorization", f"Bearer {TOKEN}")
        req.add_header("Accept", "application/vnd.github+json")
    opener = urllib.request.build_opener() if token else urllib.request.build_opener(NoRedirect)
    if not token:
        # the signed URL must not receive the token, and follow is fine without it
        opener = urllib.request.build_opener()
    with opener.open(req, timeout=60) as r:
        return r.read()


def main() -> int:
    runs = json.loads(open_(f"{API}/repos/{REPO}/actions/runs?per_page=3", True))["workflow_runs"]
    run = runs[0]
    print(f"run {run['id']} {run['head_branch']} {run['status']}/{run['conclusion']}")

    jobs = json.loads(open_(f"{API}/repos/{REPO}/actions/runs/{run['id']}/jobs", True))["jobs"]
    for job in jobs:
        print(f"  {job['name']:26} {job['conclusion'] or job['status']}")
        if job["name"] != WANT_JOB or job["conclusion"] not in ("failure", "cancelled"):
            continue

        print(f"\n=== steps of {job['name']} ===")
        for step in job.get("steps", []):
            mark = "FAIL" if step.get("conclusion") == "failure" else "    "
            print(f"  {mark} {step['number']:2}. {step['name']}")

        # resolve the redirect first, then fetch without the token
        req = urllib.request.Request(
            f"{API}/repos/{REPO}/actions/jobs/{job['id']}/logs",
            headers={"User-Agent": "ci-log", "Authorization": f"Bearer {TOKEN}"},
        )
        opener = urllib.request.build_opener(NoRedirect)
        try:
            opener.open(req, timeout=60)
        except urllib.error.HTTPError as e:
            if e.code != 302:
                raise
            location = e.headers.get("Location")
        else:
            location = None
        if not location:
            print("  (no redirect returned)")
            return 1

        text = open_(location, False).decode("utf-8", "replace")
        lines = text.splitlines()

        print("\n=== relevant log lines ===")
        keys = ("Error", "error", "Traceback", "FAILED", "iscc", "ISCC", "Compiler", "compile",
                "Error on", "error on", "[spec]")
        hit = [i for i, l in enumerate(lines) if any(k in l for k in keys)]
        shown: set[int] = set()
        for i in hit[-25:]:
            for j in range(max(0, i - 2), min(len(lines), i + 3)):
                if j not in shown:
                    print("  " + SCRUB.sub("[REDACTED]", lines[j]))
                    shown.add(j)
        if not hit:
            print("  (no obvious error lines; printing the tail)")
            for l in lines[-30:]:
                print("  " + SCRUB.sub("[REDACTED]", l))
    return 0


if __name__ == "__main__":
    sys.exit(main())
