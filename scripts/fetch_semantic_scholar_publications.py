#!/usr/bin/env python3
"""Fetch Semantic Scholar publications for the Jekyll publications section."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.local"
OUTPUT_FILE = ROOT / "_data" / "semantic_scholar_publications.json"
BASE_URL = "https://api.semanticscholar.org/graph/v1"
DEFAULT_AUTHOR_ID = "2278229261"
MAX_RETRIES = 3

MANUAL_TLDRS = {
    "bfd9d51e4631bbd520721407366b07570fe94c2d": (
        "Republican-leaning posts were more toxic during the 2024 U.S. election, "
        "but Democratic-leaning posts received more toxic replies because Republican users "
        "produced a larger share of cross-partisan replies."
    ),
}

AUTHOR_FIELDS = "name,url,paperCount,citationCount,hIndex,affiliations"
PAPER_FIELDS = ",".join(
    [
        "title",
        "url",
        "year",
        "publicationDate",
        "venue",
        "publicationVenue",
        "externalIds",
        "authors",
        "citationCount",
        "influentialCitationCount",
        "openAccessPdf",
        "publicationTypes",
        "abstract",
    ]
)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class SemanticScholarClient:
    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key
        self.last_request_at = 0.0

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = f"?{urlencode(params or {})}" if params else ""

        for attempt in range(MAX_RETRIES):
            try:
                return self._request_json(path, query)
            except RuntimeError as error:
                if "HTTP 429" not in str(error) or attempt == MAX_RETRIES - 1:
                    raise

                delay = 10 * (attempt + 1)
                print(
                    f"Semantic Scholar rate limit hit; retrying in {delay}s "
                    f"({attempt + 1}/{MAX_RETRIES - 1})...",
                    file=sys.stderr,
                )
                time.sleep(delay)

        raise RuntimeError("Semantic Scholar request failed after retries")

    def _request_json(self, path: str, query: str) -> dict[str, Any]:
        if self.api_key:
            elapsed = time.monotonic() - self.last_request_at
            if elapsed < 2.0:
                time.sleep(2.0 - elapsed)

        request = Request(f"{BASE_URL}{path}{query}")
        if self.api_key:
            request.add_header("x-api-key", self.api_key)

        try:
            with urlopen(request, timeout=30) as response:
                self.last_request_at = time.monotonic()
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            message = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Semantic Scholar request failed: HTTP {error.code}: {message}") from error
        except URLError as error:
            raise RuntimeError(f"Semantic Scholar request failed: {error.reason}") from error


def arxiv_links(arxiv_id: str | None) -> dict[str, str]:
    if not arxiv_id:
        return {}
    return {
        "arxiv_abs": f"https://arxiv.org/abs/{arxiv_id}",
        "arxiv_pdf": f"https://arxiv.org/pdf/{arxiv_id}",
    }


def doi_link(doi: str | None) -> str | None:
    return f"https://doi.org/{doi}" if doi else None


def venue_name(paper: dict[str, Any]) -> str:
    publication_venue = paper.get("publicationVenue") or {}
    if publication_venue.get("name"):
        return publication_venue["name"]
    if paper.get("venue"):
        return paper["venue"]
    if (paper.get("externalIds") or {}).get("ArXiv"):
        return "arXiv preprint"
    return "Publication venue unavailable"


def publication_label(paper: dict[str, Any]) -> str:
    publication_types = paper.get("publicationTypes") or []
    if "JournalArticle" in publication_types:
        return "Journal article"
    if (paper.get("externalIds") or {}).get("ArXiv"):
        return "Preprint"
    return "Publication"


def abbreviated_author_name(name: str | None, is_me: bool) -> str | None:
    if not name or is_me:
        return name

    parts = name.replace(".", "").split()
    if len(parts) < 2:
        return name

    family_name = parts[-1]
    given_names = parts[:-1]
    initials = []
    for part in given_names:
        initials.extend(f"{segment[0].upper()}." for segment in part.split("-") if segment)

    return f"{family_name}, {'-'.join(initials)}"


def primary_link(links: dict[str, str]) -> dict[str, str] | None:
    if links.get("doi"):
        return {"label": "DOI", "url": links["doi"]}
    if links.get("arxiv_abs"):
        return {"label": "arXiv", "url": links["arxiv_abs"]}
    if links.get("semantic_scholar"):
        return {"label": "Semantic Scholar", "url": links["semantic_scholar"]}
    return None


def abstract_fallback(abstract: str | None) -> str | None:
    if not abstract:
        return None

    sentence_end = abstract.find(". ")
    if sentence_end == -1:
        return abstract
    return abstract[: sentence_end + 1]


def normalize_paper(paper: dict[str, Any], author_id: str) -> dict[str, Any]:
    external_ids = paper.get("externalIds") or {}
    open_access_pdf = paper.get("openAccessPdf") or {}
    links = {
        "semantic_scholar": paper.get("url"),
        "doi": doi_link(external_ids.get("DOI")),
        "pdf": open_access_pdf.get("url") or None,
        **arxiv_links(external_ids.get("ArXiv")),
    }

    normalized_links = {key: value for key, value in links.items() if value}

    return {
        "paper_id": paper.get("paperId"),
        "title": paper.get("title"),
        "year": paper.get("year"),
        "publication_date": paper.get("publicationDate"),
        "venue": venue_name(paper),
        "label": publication_label(paper),
        "tldr": ((paper.get("tldr") or {}).get("text"))
        or MANUAL_TLDRS.get(paper.get("paperId"))
        or abstract_fallback(paper.get("abstract")),
        "citation_count": paper.get("citationCount") or 0,
        "influential_citation_count": paper.get("influentialCitationCount") or 0,
        "authors": [
            {
                "author_id": author.get("authorId"),
                "name": author.get("name"),
                "is_me": author.get("authorId") == author_id,
                "display_name": abbreviated_author_name(
                    author.get("name"),
                    author.get("authorId") == author_id,
                ),
            }
            for author in paper.get("authors", [])
        ],
        "external_ids": external_ids,
        "links": normalized_links,
        "primary_link": primary_link(normalized_links),
    }


def sort_key(paper: dict[str, Any]) -> tuple[str, int]:
    return (paper.get("publication_date") or "", paper.get("year") or 0)


def fetch_all_papers(client: SemanticScholarClient, author_id: str) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    offset = 0
    limit = 100

    while True:
        response = client.get_json(
            f"/author/{author_id}/papers",
            {"fields": PAPER_FIELDS, "limit": limit, "offset": offset},
        )
        batch = response.get("data", [])
        for paper in batch:
            if paper.get("paperId"):
                detail = client.get_json(f"/paper/{paper['paperId']}", {"fields": "tldr,abstract"})
                paper["tldr"] = detail.get("tldr")
                paper["abstract"] = detail.get("abstract")
            papers.append(normalize_paper(paper, author_id))

        next_offset = response.get("next")
        if next_offset is None:
            break
        offset = next_offset

    return sorted(papers, key=sort_key, reverse=True)


def main() -> int:
    load_env_file(ENV_FILE)
    author_id = os.environ.get("SEMANTIC_SCHOLAR_AUTHOR_ID", DEFAULT_AUTHOR_ID)
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")

    client = SemanticScholarClient(api_key)
    try:
        author = client.get_json(f"/author/{author_id}", {"fields": AUTHOR_FIELDS})
        papers = fetch_all_papers(client, author_id)
    except RuntimeError as error:
        if OUTPUT_FILE.exists():
            print(f"{error}", file=sys.stderr)
            print(
                f"Keeping existing {OUTPUT_FILE.relative_to(ROOT)} so the site can still build.",
                file=sys.stderr,
            )
            return 0
        raise

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(
            {
                "source": {
                    "provider": "Semantic Scholar Academic Graph API",
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                },
                "author": {
                    "author_id": author.get("authorId"),
                    "name": author.get("name"),
                    "url": author.get("url"),
                    "affiliations": author.get("affiliations") or [],
                    "paper_count": author.get("paperCount") or len(papers),
                    "citation_count": author.get("citationCount") or 0,
                    "h_index": author.get("hIndex") or 0,
                },
                "papers": papers,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(papers)} papers to {OUTPUT_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
