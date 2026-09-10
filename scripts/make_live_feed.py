"""Generate the live demo feed for the landing page.

Runs gigwatch against all configured sources, filters + ranks the matches,
and writes a compact JSON snapshot to ``live-feed.json``. A GitHub Actions
job runs this on a schedule and commits the result, so the landing page can
show *genuinely fresh* job data instead of a frozen screenshot.

Usage:
    python scripts/make_live_feed.py [output.json]

No API key is required: ranking uses the deterministic heuristic engine, so
the feed is reproducible and never depends on a paid LLM call.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from gigwatch.config import Config
from gigwatch.filtering import filter_jobs
from gigwatch.ranking import rank_jobs
from gigwatch.sources import fetch

# A demo profile: senior Python backend, remote. Broad enough to match real
# jobs on the public boards, specific enough to look intentional.
_PROFILE = {
    "title": "Senior Python Backend Engineer",
    "skills": ["python", "backend", "api", "django", "fastapi"],
    "location": "remote",
    "notes": "senior, remote-first",
}
_FILTERS = {
    "keywords": ["python", "backend", "api", "django", "fastapi", "senior"],
    "require_all_keywords": False,
    "categories": [],
    "locations": [],
    "min_score": 1.0,
    "exclude_keywords": ["intern"],
}


def _job_dict(j, score, matched):
    return {
        "title": j.title,
        "company": j.company or "",
        "salary": j.salary or "",
        "location": j.location or "",
        "url": j.url,
        "score": score,
        "matched": matched,
    }


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("live-feed.json")

    cfg = Config.from_dict({
        "sources": [{"type": t} for t in ("remotive", "wwr", "remoteok", "hn")],
        "profile": _PROFILE,
        "filters": _FILTERS,
        "alerts": {"console": False},
        "state_file": "/dev/null",
        "poll_interval": 900,
    })

    jobs = []
    errors = []
    for src in cfg.sources:
        if not src.enabled:
            continue
        try:
            got = fetch(src)
            jobs.extend(got)
        except Exception as exc:  # noqa: BLE001
            errors.append("%s: %s" % (src.type, exc))

    scored = filter_jobs(jobs, cfg.filters)
    ranked = rank_jobs(scored, _PROFILE, use_ai=False)  # heuristic: no key needed

    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sources_scanned": len([s for s in cfg.sources if s.enabled]),
        "jobs_fetched": len(jobs),
        "matches": len(ranked),
        "errors": errors,
        "jobs": [
            _job_dict(r.job, r.score, r.matched_keywords) for r in ranked
        ],
    }
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("wrote %s: %d fetched, %d matches" % (out, len(jobs), len(ranked)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
