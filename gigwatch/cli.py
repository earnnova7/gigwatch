"""GigWatch command-line interface.

Commands:
  init      Write a starter config file.
  scan      One-shot: fetch, filter, dedupe, alert, update state.
  watch     Loop `scan` on an interval (for a cron-less daemon).
  list      Dry run: fetch + filter + print matches, WITHOUT touching state.
  reset     Clear the seen-state so everything can alert again.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import List

from gigwatch import __version__
from gigwatch.alerts import send_all
from gigwatch.config import Config, load_config
from gigwatch.filtering import filter_jobs
from gigwatch.sources import Job, fetch
from gigwatch.state import load_state, mark_seen, prune, save_state

DEFAULT_CONFIG = "config.json"


def _log(msg: str, verbose: bool = False, err: bool = False) -> None:
    if err:
        print("[gigwatch] " + msg, file=sys.stderr)
    elif verbose:
        print("[gigwatch] " + msg, file=sys.stderr)


def _fetch_all(cfg: Config, verbose: bool) -> (List[Job], List[str]):
    """Fetch every enabled source; collect per-source errors, keep going."""
    jobs: List[Job] = []
    errors: List[str] = []
    for src in cfg.sources:
        if not src.enabled:
            continue
        try:
            got = fetch(src)
            jobs.extend(got)
            _log("fetched %d job(s) from %s" % (len(got), src.type), verbose)
        except Exception as exc:  # noqa: BLE001 - keep going on one bad source
            errors.append("%s: %s" % (src.type, exc))
            _log("source %s failed: %s" % (src.type, exc), verbose, err=True)
    return jobs, errors


def cmd_init(args) -> int:
    path = args.config
    if os.path.exists(path) and not args.force:
        print("config already exists at %s (use --force to overwrite)" % path,
              file=sys.stderr)
        return 1
    starter = {
        "sources": [{"type": "remotive"}],
        "filters": {
            "keywords": ["python", "backend", "api"],
            "require_all_keywords": False,
            "categories": [],
            "locations": [],
            "min_score": 1.0,
            "exclude_keywords": ["intern"],
        },
        "alerts": {
            "console": True,
            "email": {
                "to": "${GIGWATCH_EMAIL_TO}",
                "from": "gigwatch@localhost",
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "use_tls": True,
                "username": "${GIGWATCH_SMTP_USER}",
                "password": "${GIGWATCH_SMTP_PASS}",
            },
            "slack": {"webhook_url": "${GIGWATCH_SLACK_WEBHOOK}"},
            "max_per_alert": 25,
        },
        "state_file": "gigwatch-state.json",
        "poll_interval": 900,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(starter, fh, indent=2)
        fh.write("\n")
    print("wrote starter config to %s" % path)
    print("edit filters.keywords to your skills, then run: gigwatch scan")
    return 0


def cmd_scan(args) -> int:
    cfg = load_config(args.config)
    jobs, fetch_errors = _fetch_all(cfg, args.verbose)

    scored = filter_jobs(jobs, cfg.filters)
    state = load_state(cfg.state_file)
    new_matches = [s for s in scored if s.job.id not in state]

    print("scanned %d job(s) from %d source(s); %d match filter; %d new"
          % (len(jobs), len([s for s in cfg.sources if s.enabled]),
             len(scored), len(new_matches)))

    alert_errors: List[str] = []
    if new_matches:
        alert_errors = send_all(new_matches, cfg.alerts)

    # Mark every job that matched as seen (so it won't re-alert). Jobs that
    # don't match are left unmarked, so they can alert later if your filters
    # change and they start matching.
    mark_seen(state, scored)
    removed = prune(state, args.max_age_days)
    if removed:
        _log("pruned %d stale state entries" % removed, args.verbose)
    save_state(cfg.state_file, state)

    for e in fetch_errors:
        print("  [warn] " + e, file=sys.stderr)
    for e in alert_errors:
        print("  [warn] alert failed: " + e, file=sys.stderr)
    return 0


def cmd_list(args) -> int:
    cfg = load_config(args.config)
    jobs, _ = _fetch_all(cfg, args.verbose)
    scored = filter_jobs(jobs, cfg.filters)
    print("%d job(s) fetched, %d match your filters (dry run, state untouched)"
          % (len(jobs), len(scored)))
    for i, s in enumerate(scored, 1):
        j = s.job
        print("%2d. [score %s] %s" % (i, s.score, j.title))
        if j.company:
            print("     company: %s" % j.company)
        if j.salary:
            print("     salary:  %s" % j.salary)
        if j.location:
            print("     where:   %s" % j.location)
        if s.matched_keywords:
            print("     matched: %s" % ", ".join(s.matched_keywords))
        print("     %s" % j.url)
    return 0


def cmd_watch(args) -> int:
    interval = args.interval or cfg_interval(args.config)
    print("watching every %ds (Ctrl-C to stop)" % interval)
    while True:
        try:
            cmd_scan(_args_with_interval(args))
        except Exception as exc:  # noqa: BLE001 - never let a scan kill the loop
            print("[gigwatch] scan error: %s" % exc, file=sys.stderr)
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nstopped.")
            return 0


def cfg_interval(config_path: str) -> int:
    try:
        return load_config(config_path).poll_interval
    except Exception:  # noqa: BLE001
        return 900


def _args_with_interval(args):
    return args


def cmd_reset(args) -> int:
    cfg = load_config(args.config)
    if os.path.exists(cfg.state_file):
        os.remove(cfg.state_file)
        print("cleared state file %s (next scan will alert on all matches)"
              % cfg.state_file)
    else:
        print("no state file at %s (nothing to reset)" % cfg.state_file)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gigwatch",
        description="Self-hosted freelance-gig watcher: monitor job feeds, "
                    "filter by your skills, alert on new matches.",
    )
    p.add_argument("--version", action="version", version="gigwatch %s" % __version__)
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp):
        sp.add_argument("--config", default=DEFAULT_CONFIG,
                        help="path to config file (default: %s)" % DEFAULT_CONFIG)
        sp.add_argument("--verbose", "-v", action="store_true")

    sp = sub.add_parser("init", help="write a starter config file")
    add_common(sp)
    sp.add_argument("--force", action="store_true", help="overwrite if it exists")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("scan", help="one-shot scan + alert")
    add_common(sp)
    sp.add_argument("--max-age-days", type=int, default=90,
                    help="drop state entries older than this (0 = keep all)")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("list", help="dry run: show matches, no state change")
    add_common(sp)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("watch", help="loop scan on an interval")
    add_common(sp)
    sp.add_argument("--interval", type=int, default=None,
                    help="seconds between scans (default: poll_interval from config)")
    sp.add_argument("--max-age-days", type=int, default=90,
                    help="drop state entries older than this (0 = keep all)")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("reset", help="clear seen-state")
    add_common(sp)
    sp.set_defaults(func=cmd_reset)

    return p


def main(argv: List[str] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
