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
    jobs = fetch_remotive(limit=200)
    f = Filters(keywords=["python"], min_score=1.0)
    out = filter_jobs(jobs, f)
    # Remotive is a remote-work board; python roles exist there regularly.
    assert len(out) >= 1
    assert all(s.score >= 1.0 for s in out)
