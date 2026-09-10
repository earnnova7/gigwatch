"""Trigger the live-feed workflow, fetch its artifact, and push it to the repo.

The ``live-feed.yml`` workflow runs gigwatch and uploads ``live-feed.json`` as
an artifact (the default Actions token is read-only, so it can't push). This
script — run from a context that *does* have Contents:write (Nova's cron) —
triggers the workflow, waits for it to finish, downloads the artifact, and
commits + pushes the fresh feed so the landing page serves live data.

Usage:
    python scripts/push_live_feed.py            # trigger + wait + fetch + push
    python scripts/push_live_feed.py --no-wait  # fetch the latest finished run
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
import zipfile
import io
from pathlib import Path

REPO = "earnnova7/gigwatch"
WORKFLOW = "live-feed.yml"
ARTIFACT = "live-feed"
API = f"https://api.github.com/repos/{REPO}"


def _token() -> str:
    tok = os.environ.get("GITHUB_TOKEN")
    if not tok:
        env = Path(__file__).resolve().parents[2] / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                line = line.strip()
                if line.startswith("GITHUB_TOKEN="):
                    tok = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not tok:
        raise SystemExit("GITHUB_TOKEN not found (env or ~/.env)")
    return tok


def _call(method: str, url: str, body=None, raw=False, tok: str = ""):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": "token " + tok,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "nova",
        },
    )
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, (r.read() if raw else json.loads(r.read().decode() or "{}"))
    except urllib.error.HTTPError as e:
        return e.code, (e.read() if raw else json.loads(e.read().decode() or "{}"))


def trigger(tok: str) -> int:
    s, d = _call("POST", f"{API}/actions/workflows/{WORKFLOW}/dispatches",
                 {"ref": "main"}, tok=tok)
    print("trigger ->", s, d)
    return s


def latest_run(tok: str) -> dict:
    s, d = _call("GET", f"{API}/actions/runs?per_page=5", tok=tok)
    for r in d.get("workflow_runs", []):
        if r.get("name") == "Live feed":
            return r
    return {}


def wait_for_run(tok: str, timeout_s: int = 300) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = latest_run(tok)
        if r:
            status, conclusion = r.get("status"), r.get("conclusion")
            print(f"  run {r.get('id')}: status={status} conclusion={conclusion}")
            if status == "completed":
                return r
        time.sleep(12)
    print("  timed out waiting for run")
    return latest_run(tok)


def fetch_artifact(tok: str, run_id: int) -> bytes:
    s, d = _call("GET", f"{API}/actions/runs/{run_id}/artifacts", tok=tok)
    arts = d.get("artifacts", [])
    if not arts:
        raise SystemExit(f"no artifacts on run {run_id}: {d}")
    art = next((a for a in arts if a["name"] == ARTIFACT), arts[0])
    s, body = _call("GET", art["archive_download_url"], raw=True, tok=tok)
    if s != 200:
        raise SystemExit(f"artifact download failed: {s} {body[:200]}")
    z = zipfile.ZipFile(io.BytesIO(body))
    for n in z.namelist():
        if n.endswith("live-feed.json"):
            return z.read(n)
    raise SystemExit(f"live-feed.json not in artifact: {z.namelist()}")


def push(repo_dir: Path, tok: str) -> int:
    env = dict(os.environ, GITHUB_TOKEN=tok)
    def sh(cmd):
        r = subprocess.run(cmd, shell=True, cwd=repo_dir, env=env,
                           capture_output=True, text=True)
        return r.returncode, (r.stdout + r.stderr).strip()
    sh("git config user.name gigwatch-bot")
    sh("git config user.email gigwatch-bot@users.noreply.github.com")
    rc, out = sh("git add live-feed.json")
    if rc != 0:
        print("git add failed:", out)
        return rc
    rc, out = sh("git diff --cached --quiet")
    if rc == 0:
        print("feed unchanged, nothing to push")
        return 0
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    rc, out = sh(f'git commit -m "chore: refresh live feed ({ts})"')
    if rc != 0:
        print("commit failed:", out)
        return rc
    rc, out = sh("git push origin main")
    print("push ->", rc, out[-200:] if out else "")
    return rc


def main() -> int:
    tok = _token()
    repo_dir = Path(__file__).resolve().parents[1]
    no_wait = "--no-wait" in sys.argv

    if not no_wait:
        trigger(tok)
        run = wait_for_run(tok)
    else:
        run = latest_run(tok)
    if not run:
        print("no run found")
        return 1
    if run.get("conclusion") != "success":
        print("warning: run conclusion =", run.get("conclusion"), "(still trying to fetch)")

    feed = fetch_artifact(tok, run["id"])
    (repo_dir / "live-feed.json").write_bytes(feed)
    data = json.loads(feed)
    print(f"downloaded feed: {data.get('jobs_fetched')} fetched, "
          f"{data.get('matches')} matches, {data.get('sources_scanned')} sources")
    return push(repo_dir, tok)


if __name__ == "__main__":
    sys.exit(main())
