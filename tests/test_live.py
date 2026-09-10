"""Live integration tests: hit real public endpoints.

Deselected by default (see pyproject addopts). Run explicitly with:
    pytest -m live
"""

import urllib.error

import pytest

from gigwatch.sources import fetch_remoteok, fetch_remotive, fetch_wwr
from gigwatch.filtering import Filters, filter_jobs


def _fetch_or_skip(fn, **kwargs):
    """Call a live fetcher, skipping (not failing) on transient upstream errors.

    RemoteOK/WWR occasionally rate-limit or block CI egress IPs; a 403/429/5xx
    or an unreachable host is an environment problem, not a bug in the adapter.
    """
    try:
        return fn(**kwargs)
    except urllib.error.HTTPError as exc:  # noqa: PERF203
        if exc.code in (403, 429) or exc.code >= 500:
            pytest.skip("upstream returned HTTP %s" % exc.code)
        raise
    except urllib.error.URLError as exc:
        pytest.skip("network unavailable: %s" % exc)


@pytest.mark.live
def test_remotive_returns_jobs():
    jobs = fetch_remotive(limit=50)
    assert len(jobs) > 0
    j = jobs[0]
    assert j.title and j.url and j.source == "remotive"
    assert j.id


@pytest.mark.live
def test_remotive_filter_end_to_end():
    """Filter with a broad keyword set that Remotive reliably has."""
    jobs = fetch_remotive(limit=200)
    assert len(jobs) > 0, "Remotive returned no jobs at all"
    # Use keywords that are common on remote boards; the point is the
    # filter pipeline works end-to-end, not that one specific language
    # is always present.
    f = Filters(keywords=["react", "golang", "python", "java", "node"], min_score=1.0)
    out = filter_jobs(jobs, f)
    # At least one of these should match on any given day; if none do,
    # the board is empty or the API changed shape — fail loudly.
    assert len(out) >= 1, (
        f"No matches for common tech keywords among {len(jobs)} jobs. "
        f"Titles: {[j.title for j in jobs[:10]]}"
    )
    assert all(s.score >= 1.0 for s in out)


@pytest.mark.live
def test_wwr_returns_jobs():
    jobs = _fetch_or_skip(fetch_wwr, limit=50)
    assert len(jobs) > 0
    j = jobs[0]
    assert j.title and j.url and j.source == "wwr"
    assert j.id


@pytest.mark.live
def test_remoteok_returns_jobs():
    jobs = _fetch_or_skip(fetch_remoteok, limit=50)
    assert len(jobs) > 0
    j = jobs[0]
    assert j.title and j.url and j.source == "remoteok"
    assert j.id


@pytest.mark.live
def test_wwr_filter_end_to_end():
    jobs = _fetch_or_skip(fetch_wwr, limit=200)
    assert len(jobs) > 0, "WWR returned no jobs at all"
    f = Filters(keywords=["react", "golang", "python", "java", "node",
                          "engineer", "developer", "manager"], min_score=1.0)
    out = filter_jobs(jobs, f)
    assert len(out) >= 1, (
        f"No matches for common keywords among {len(jobs)} jobs. "
        f"Titles: {[j.title for j in jobs[:10]]}"
    )
