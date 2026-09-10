"""Live integration tests: hit real public endpoints.

Deselected by default (see pyproject addopts). Run explicitly with:
    pytest -m live
"""

import pytest

from gigwatch.sources import fetch_remotive
from gigwatch.filtering import Filters, filter_jobs


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
