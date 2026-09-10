"""Unit tests for GigWatch. No network required (see tests/test_live.py)."""

import json
import os
import time

import pytest

from gigwatch.config import Config, Filters, load_config
from gigwatch.filtering import filter_jobs, score_job
from gigwatch.sources import Job
from gigwatch.state import load_state, mark_seen, new_ids, prune, save_state
from gigwatch.alerts import format_jobs
from gigwatch.filtering import ScoredJob


def make_job(jid="j1", title="Senior Python Backend Engineer",
             company="Acme", url="https://example.com/j/1",
             category="Information Technology", location="Remote (Worldwide)",
             salary="$120k-$150k", tags=["python", "django"],
             description="Build APIs with Python and Django."):
    return Job(id=jid, title=title, company=company, url=url, category=category,
               location=location, salary=salary, tags=tags,
               published="2026-09-01T00:00:00", source="test",
               description=description)


# ---------- filtering ----------

def test_keyword_any_match():
    f = Filters(keywords=["python", "rust"])
    jobs = [make_job(title="Python Backend Dev"), make_job(title="Rust Systems Dev"),
            make_job(title="Graphic Designer")]
    out = filter_jobs(jobs, f)
    assert [s.job.id for s in out] == ["j1", "j1", "j1"][:2] or len(out) == 2
    titles = {s.job.title for s in out}
    assert "Graphic Designer" not in titles

def test_keyword_all_match():
    f = Filters(keywords=["python", "django"], require_all_keywords=True)
    jobs = [make_job(title="Python Backend Dev"),
            make_job(title="Django Developer")]
    out = filter_jobs(jobs, f)
    assert len(out) == 0  # neither job has BOTH words

def test_exclude_keyword_blocks():
    f = Filters(keywords=["python"], exclude_keywords=["intern"])
    jobs = [make_job(title="Python Intern"), make_job(title="Python Engineer")]
    out = filter_jobs(jobs, f)
    assert [s.job.title for s in out] == ["Python Engineer"]

def test_category_filter():
    f = Filters(keywords=["python"], categories=["design"])
    jobs = [make_job(title="Python Dev", category="Information Technology")]
    assert filter_jobs(jobs, f) == []

def test_location_filter():
    f = Filters(keywords=["python"], locations=["worldwide"])
    jobs = [make_job(title="Python Dev", location="Remote (Worldwide)"),
            make_job(title="Python Dev", location="New York, USA")]
    out = filter_jobs(jobs, f)
    assert len(out) == 1 and "Worldwide" in out[0].job.location

def test_min_score_threshold():
    f = Filters(keywords=["python", "django"], min_score=4.0)
    # only one keyword in title -> score 3.0 < 4.0
    job = make_job(title="Python Dev", description="uses django in prod")
    out = filter_jobs([job], f)
    assert out == []

def test_score_title_hits_count_more():
    f = Filters(keywords=["python", "api"])
    title_hit = make_job(title="Python API Engineer", description="misc")
    body_hit = make_job(jid="j2", title="Backend Engineer",
                        description="python api work")
    assert score_job(title_hit, f) > score_job(body_hit, f)

def test_no_keywords_matches_everything():
    f = Filters(keywords=[])
    out = filter_jobs([make_job()], f)
    assert len(out) == 1 and out[0].score == 1.0


# ---------- state ----------

def test_state_roundtrip(tmp_path):
    p = str(tmp_path / "state.json")
    state = load_state(p)
    assert state == {}
    mark_seen(state, [ScoredJob(job=make_job("a"), score=1, matched_keywords=[])])
    save_state(p, state)
    again = load_state(p)
    assert again == state and "a" in again

def test_new_ids_only_unseen(tmp_path):
    p = str(tmp_path / "state.json")
    state = load_state(p)
    a, b = make_job("a"), make_job("b")
    mark_seen(state, [ScoredJob(job=a, score=1, matched_keywords=[])])
    save_state(p, state)
    state = load_state(p)
    fresh = [ScoredJob(job=a, score=1, matched_keywords=[]),
             ScoredJob(job=b, score=1, matched_keywords=[])]
    new = new_ids(state, fresh)
    assert [j.job.id for j in new] == ["b"]

def test_prune_drops_old_entries():
    state = {}
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(0))  # 1970
    state["old"] = old
    state["new"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    removed = prune(state, max_age_days=90)
    assert removed == 1 and "new" in state and "old" not in state

def test_prune_zero_keeps_all():
    state = {"x": "1970-01-01T00:00:00Z"}
    assert prune(state, max_age_days=0) == 0 and "x" in state


# ---------- config ----------

def test_load_config_minimal(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"sources": [{"type": "remotive"}]}))
    cfg = load_config(str(p))
    assert len(cfg.sources) == 1 and cfg.sources[0].type == "remotive"
    assert cfg.state_file == "gigwatch-state.json"

def test_load_config_rejects_bad_source(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"sources": [{"type": "nope"}]}))
    with pytest.raises(ValueError):
        load_config(str(p))

def test_load_config_requires_source_for_rss(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"sources": [{"type": "rss"}]}))
    with pytest.raises(ValueError):
        load_config(str(p))

def test_env_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGWATCH_EMAIL_TO", "me@example.com")
    p = tmp_path / "c.json"
    p.write_text(json.dumps({
        "sources": [{"type": "remotive"}],
        "alerts": {"console": True, "email": {"to": "${GIGWATCH_EMAIL_TO}"}},
    }))
    cfg = load_config(str(p))
    assert cfg.alerts.email["to"] == "me@example.com"


# ---------- alerts formatting ----------

def test_format_jobs_output():
    s = ScoredJob(job=make_job(), score=6.0, matched_keywords=["python"])
    text = format_jobs([s], max_per_alert=5)
    assert "1 new matching gig" in text
    assert "Senior Python Backend Engineer" in text
    assert "Acme" in text
    assert "https://example.com/j/1" in text
    assert "python" in text
