"""Filtering and relevance scoring for matched jobs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from gigwatch.config import Filters
from gigwatch.sources import Job


@dataclass
class ScoredJob:
    job: Job
    score: float
    matched_keywords: List[str]


def _match_keywords(job: Job, filters: Filters) -> List[str]:
    # Keyword matching (any/all-match, incl. require_all_keywords) is
    # evaluated against the TITLE only. The title is the reliable signal for
    # what a role is; descriptions and other free text can mention a keyword
    # incidentally ("we use Python internally") and would otherwise create
    # false matches.
    hay = job.title.lower()
    matched = [k for k in filters.keywords if k in hay]
    if filters.exclude_keywords:
        # Exclude keywords are a safety net: they check the title AND the
        # description, so a job that mentions an excluded term in its body
        # (e.g. "intern") is blocked even when the title is clean.
        excl = hay + " " + job.description.lower()
        for k in filters.exclude_keywords:
            if k in excl:
                return []  # excluded
    if not filters.keywords:
        return []
    if filters.require_all_keywords:
        return matched if len(matched) == len(filters.keywords) else []
    return matched


def _match_category(job: Job, filters: Filters) -> bool:
    if not filters.categories:
        return True
    cat = job.category.lower()
    loc = job.location.lower()
    return any(c in cat or c in loc for c in filters.categories)


def _match_location(job: Job, filters: Filters) -> bool:
    if not filters.locations:
        return True
    loc = job.location.lower()
    return any(l in loc for l in filters.locations)


def score_job(job: Job, filters: Filters) -> float:
    """Relevance score: 3.0 per keyword found in the title.

    Only the title is scored. A keyword that appears solely in the description
    (or other free text) is too noisy to count toward relevance — it would let
    a job that merely mentions a skill in passing clear ``min_score``.
    """
    if not filters.keywords:
        return 1.0
    title = job.title.lower()
    score = 0.0
    for k in filters.keywords:
        if k in title:
            score += 3.0
    return round(score, 2)


def filter_jobs(jobs: List[Job], filters: Filters) -> List[ScoredJob]:
    """Return jobs that pass all filters, sorted by score (desc)."""
    out: List[ScoredJob] = []
    for job in jobs:
        matched = _match_keywords(job, filters)
        if filters.keywords and not matched:
            continue
        if not _match_category(job, filters):
            continue
        if not _match_location(job, filters):
            continue
        score = score_job(job, filters)
        if score < filters.min_score:
            continue
        out.append(ScoredJob(job=job, score=score, matched_keywords=matched))
    out.sort(key=lambda s: s.score, reverse=True)
    return out
