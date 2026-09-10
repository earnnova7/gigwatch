"""Refresh the landing-page live feed: regenerate, and push only if it changed.

Run this from a context with Contents:write (Nova's cron). It regenerates
``live-feed.json`` from the live job boards and commits + pushes it ONLY when
the content actually changed — so a 30-minute cron cadence produces at most a
few commits a day (job boards change slowly), not one per tick.

Usage:
    python scripts/refresh_feed.py
Prints a one-line summary: fetched/match counts and whether it pushed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]


def _token() -> str:
    tok = os.environ.get("GITHUB_TOKEN")
    if not tok:
        for cand in (Path(__file__).resolve().parents[3] / ".env",
                     Path(__file__).resolve().parents[2] / ".env",
                     Path.home() / ".env"):
            if cand.exists():
                for line in cand.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("GITHUB_TOKEN="):
                        tok = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
                if tok:
                    break
    if not tok:
        raise SystemExit("GITHUB_TOKEN not found (env or ~/.env)")
    return tok


def _sh(cmd: str, env=None) -> tuple[int, str]:
    r = subprocess.run(cmd, shell=True, cwd=REPO_DIR, env=env,
                       capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def _content_hash(path: Path) -> str:
    """Hash the feed ignoring the volatile generated_at timestamp, so a
    re-run with identical job data doesn't count as a change."""
    d = json.loads(path.read_text())
    d.pop("generated_at", None)
    return json.dumps(d, sort_keys=True)


def main() -> int:
    # 1) Regenerate the feed from the live job boards.
    rc, out = _sh(f"{sys.executable} scripts/make_live_feed.py live-feed.json")
    if rc != 0:
        print(f"generate failed: {out[-300:]}")
        return rc

    # 2) Compare against the committed feed, ignoring the timestamp. If the
    #    actual job data is unchanged, stop (no spammy commit every tick).
    new = _content_hash(REPO_DIR / "live-feed.json")
    rc, old = _sh("git show HEAD:live-feed.json")
    if rc == 0:
        import hashlib
        old_d = json.loads(old)
        old_d.pop("generated_at", None)
        old = json.dumps(old_d, sort_keys=True)
    else:
        old = ""
    if new == old:
        print("feed unchanged — nothing to push")
        return 0

    # 3) Commit + push with the token.
    tok = _token()
    env = dict(os.environ, GITHUB_TOKEN=tok)
    _sh("git config user.name gigwatch-bot", env)
    _sh("git config user.email gigwatch-bot@users.noreply.github.com", env)
    _sh("git add live-feed.json", env)
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    rc, out = _sh(f'git commit -m "chore: refresh live feed ({ts})"', env)
    if rc != 0:
        print(f"commit failed: {out[-300:]}")
        return rc
    rc, out = _sh("git push origin main", env)
    if rc != 0:
        print(f"push failed: {out[-300:]}")
        return rc

    data = json.loads((REPO_DIR / "live-feed.json").read_text())
    print(f"pushed live feed: {data.get('jobs_fetched')} fetched, "
          f"{data.get('matches')} matches, {data.get('sources_scanned')} sources")
    return 0


if __name__ == "__main__":
    sys.exit(main())
