"""Job/gig feed sources.

Each source fetches a list of normalized :class:`Job` objects. Sources are
pure functions of the network + config, so they are easy to test and extend.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

USER_AGENT = "GigWatch/0.1 (+https://github.com/earnnova7/gigwatch)"


@dataclass
class Job:
    """A normalized job/gig listing."""

    id: str
    title: str
    company: str
    url: str
    category: str = ""
    location: str = ""
    salary: str = ""
    tags: List[str] = field(default_factory=list)
    published: str = ""
    source: str = ""
    description: str = ""

    def haystack(self) -> str:
        """Lowercased text used for keyword matching."""
        return " ".join(
            [self.title, self.company, self.category, self.location,
             self.salary, " ".join(self.tags), self.description]
        ).lower()


def _http_get(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _clean(text: str) -> str:
    """Strip tags and collapse whitespace from a (possibly HTML) string."""
    if not text:
        return ""
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    import html
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_remotive(limit: Optional[int] = None) -> List[Job]:
    """Fetch live remote jobs from Remotive's public API (no auth required)."""
    url = "https://remotive.com/api/remote-jobs"
    data = json.loads(_http_get(url).decode("utf-8"))
    jobs: List[Job] = []
    for raw in data.get("jobs", []):
        jobs.append(
            Job(
                id=str(raw.get("id")),
                title=_clean(raw.get("title", "")),
                company=_clean(raw.get("company_name", "")),
                url=raw.get("url", ""),
                category=_clean(raw.get("category", "")),
                location=_clean(raw.get("candidate_required_location", "")),
                salary=_clean(raw.get("salary", "")),
                tags=[_clean(t) for t in raw.get("tags", []) if t],
                published=raw.get("publication_date", ""),
                source="remotive",
                description=_clean(raw.get("description", "")),
            )
        )
    if limit:
        jobs = jobs[:limit]
    return jobs


def fetch_rss(url: str, limit: Optional[int] = None) -> List[Job]:
    """Fetch jobs from an RSS/Atom feed (works for many job boards)."""
    root = ET.fromstring(_http_get(url).decode("utf-8", "replace"))
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    jobs: List[Job] = []

    # RSS 2.0: <channel><item>
    items = root.findall(".//item")
    for it in items:
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = _clean(it.findtext("description") or "")
        pub = (it.findtext("pubDate") or "").strip()
        jobs.append(_rss_job(title, link, desc, pub, source="rss"))

    # Atom: <entry>
    if not items:
        entries = root.findall("atom:entry", ns)
        for it in entries:
            title = (it.findtext("atom:title", namespaces=ns) or "").strip()
            link_el = it.find("atom:link[@rel='alternate']", ns)
            if link_el is None:
                link_el = it.find("atom:link", ns)
            link = (link_el.get("href") if link_el is not None else "") or ""
            desc = _clean(it.findtext("atom:summary", namespaces=ns) or "")
            pub = (it.findtext("atom:updated", namespaces=ns) or "").strip()
            jobs.append(_rss_job(title, link, desc, pub, source="rss"))

    if limit:
        jobs = jobs[:limit]
    return [j for j in jobs if j.id]


def _rss_job(title: str, link: str, desc: str, pub: str, source: str) -> Job:
    import hashlib
    jid = hashlib.sha1((link or title).encode("utf-8")).hexdigest()[:16]
    return Job(
        id=jid,
        title=title,
        company="",
        url=link,
        description=desc,
        published=pub,
        source=source,
    )


def fetch_json(url: str, limit: Optional[int] = None) -> List[Job]:
    """Fetch jobs from a JSON endpoint returning a list of objects.

    Expects each object to have at least `title` and `url`. Other common keys
    (company/company_name, category, location, salary, tags, publication_date/
    published) are mapped if present.
    """
    data = json.loads(_http_get(url).decode("utf-8", "replace"))
    if isinstance(data, dict):
        # tolerate {"jobs": [...]} / {"data": [...]}
        for key in ("jobs", "data", "results", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise ValueError("json source must return a list of job objects")

    jobs: List[Job] = []
    for i, raw in enumerate(data):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("name") or "").strip()
        url = str(raw.get("url") or raw.get("link") or "").strip()
        if not title and not url:
            continue
        jobs.append(
            Job(
                id=str(raw.get("id") or hashlib_sha1(url or title)),
                title=title,
                company=str(raw.get("company") or raw.get("company_name") or ""),
                url=url,
                category=str(raw.get("category") or ""),
                location=str(raw.get("location") or raw.get("country") or ""),
                salary=str(raw.get("salary") or ""),
                tags=[str(t) for t in (raw.get("tags") or [])],
                published=str(raw.get("publication_date") or raw.get("published") or ""),
                source="json",
                description=_clean(str(raw.get("description") or "")),
            )
        )
    if limit:
        jobs = jobs[:limit]
    return jobs


def _hashlib_sha1(s: str) -> str:
    import hashlib
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def fetch(source) -> List[Job]:
    """Dispatch to the right fetcher for a :class:`SourceConfig`."""
    if source.type == "remotive":
        return fetch_remotive(source.limit)
    if source.type == "rss":
        return fetch_rss(source.url, source.limit)
    if source.type == "json":
        return fetch_json(source.url, source.limit)
    raise ValueError("unknown source type: %r" % source.type)
