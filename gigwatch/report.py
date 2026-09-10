"""Render matched jobs in different output formats.

Used by the ``scan`` and ``list`` commands via their ``--format`` flag:

* ``text`` (default) - the indented human-readable listing;
* ``markdown`` - a GitHub-flavoured table (``#``, Title, Company, Salary,
  Location, Score, URL);
* ``json`` - an array of job objects (every :class:`~gigwatch.sources.Job`
  field, plus ``score`` and ``matched_keywords``).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import List

from gigwatch.filtering import ScoredJob

FORMATS = ("text", "markdown", "json")

_MD_COLUMNS = ("#", "Title", "Company", "Salary", "Location", "Score", "URL")


def render(scored: List[ScoredJob], fmt: str = "text") -> str:
    """Return *scored* rendered as *fmt* (one of :data:`FORMATS`)."""
    if fmt == "text":
        return _render_text(scored)
    if fmt == "markdown":
        return _render_markdown(scored)
    if fmt == "json":
        return _render_json(scored)
    raise ValueError("unknown format: %r" % fmt)


def _render_text(scored: List[ScoredJob]) -> str:
    lines: List[str] = []
    for i, s in enumerate(scored, 1):
        j = s.job
        lines.append("%2d. [score %s] %s" % (i, s.score, j.title))
        if j.company:
            lines.append("     company: %s" % j.company)
        if j.salary:
            lines.append("     salary:  %s" % j.salary)
        if j.location:
            lines.append("     where:   %s" % j.location)
        if s.matched_keywords:
            lines.append("     matched: %s" % ", ".join(s.matched_keywords))
        lines.append("     %s" % j.url)
    return "\n".join(lines)


def _md_cell(value) -> str:
    """Sanitise a value for use inside a Markdown table cell."""
    text = str(value).replace("|", "\\|").replace("\n", " ").strip()
    return text or "-"


def _render_markdown(scored: List[ScoredJob]) -> str:
    rows = [
        "| " + " | ".join(_MD_COLUMNS) + " |",
        "|" + "|".join(["---"] * len(_MD_COLUMNS)) + "|",
    ]
    for i, s in enumerate(scored, 1):
        j = s.job
        rows.append(
            "| " + " | ".join(
                [
                    str(i),
                    _md_cell(j.title),
                    _md_cell(j.company),
                    _md_cell(j.salary),
                    _md_cell(j.location),
                    _md_cell(s.score),
                    _md_cell(j.url),
                ]
            ) + " |"
        )
    return "\n".join(rows)


def _render_json(scored: List[ScoredJob]) -> str:
    out = []
    for s in scored:
        obj = asdict(s.job)
        obj["score"] = s.score
        obj["matched_keywords"] = list(s.matched_keywords)
        out.append(obj)
    return json.dumps(out, indent=2, ensure_ascii=False)
