#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Fetch publications from an arXiv author profile page and generate a BibTeX file.

This script is designed to mimic the effect of Franklin's \publist macro:
it uses the arXiv author identifier page (e.g. https://arxiv.org/a/wang_t_9.html),
fetches the corresponding Atom2 feed, and extracts metadata for each paper.

Output:
    - content/publications.bib

Usage:
    - Run from the repository root:
        python scripts/update_publications_from_arxiv.py
"""

import os
import re
import textwrap
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

import feedparser
import requests


# ------------- Configuration -------------

# Your arXiv author profile page.
AUTHOR_PROFILE_URL = "https://arxiv.org/a/wang_t_9.html"

# Output BibTeX file path (relative to repo root).
OUTPUT_BIB = os.path.join("content", "cv.md")

# Maximum number of entries to fetch (can be large, Atom feed is paginated by arXiv).
MAX_ENTRIES = 500


# ------------- Data structures -------------

@dataclass
class ArxivEntry:
    """Container for a single arXiv entry."""
    arxiv_id: str
    title: str
    authors: List[str]
    year: int
    published: datetime
    primary_category: Optional[str]
    journal_ref: Optional[str]
    doi: Optional[str]
    url: str


# ------------- Utility functions -------------

def author_profile_to_atom2_url(profile_url: str) -> str:
    """
    Convert an arXiv author profile HTML URL to the Atom2 feed URL.

    Example:
        https://arxiv.org/a/wang_t_9.html -> https://arxiv.org/a/wang_t_9.atom2
    """
    parsed = urlparse(profile_url)
    # Path is of the form "/wang_t_9.html"
    slug = os.path.basename(parsed.path)
    # Remove .html suffix if present
    if slug.endswith(".html"):
        slug = slug[:-5]
    # Construct the Atom2 feed URL
    return f"https://arxiv.org/a/{slug}.atom2"


def clean_whitespace(text: str) -> str:
    """Normalize whitespace in a string."""
    return re.sub(r"\s+", " ", text).strip()


def make_bibtex_key(entry: ArxivEntry) -> str:
    """
    Generate a BibTeX key of the form:
        lastnameYYYYshorttitle
    where shorttitle is a compact slug from the title.

    This does not attempt to be perfectly collision-free, but
    it is usually good enough for a personal publication list.
    """
    # Get first author's last name
    if entry.authors:
        first_author = entry.authors[0]
        # Split on spaces, take last token as "last name"
        last_name = first_author.split()[-1]
    else:
        last_name = "unknown"

    last_name = re.sub(r"[^A-Za-z]", "", last_name).lower() or "unknown"

    # Create a short slug from the title
    title_slug = re.sub(r"[^A-Za-z0-9]+", " ", entry.title)
    title_slug = title_slug.lower().strip()
    words = title_slug.split()
    short = "".join(words[:4])  # first few words concatenated

    return f"{last_name}{entry.year}{short}"


def format_authors_bibtex(authors: List[str]) -> str:
    """
    Format authors for BibTeX: "Last, First and Last, First and ..."
    For simplicity, we keep the names as they appear in the feed and join with ' and '.
    """
    return " and ".join(authors)


def fetch_atom_feed(atom_url: str) -> feedparser.FeedParserDict:
    """
    Fetch the Atom2 feed and parse it with feedparser.
    Raises an exception if the HTTP request fails.
    """
    resp = requests.get(atom_url, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.text)
    return feed


def parse_entries(feed: feedparser.FeedParserDict) -> List[ArxivEntry]:
    """
    Convert the Atom feed entries into a list of ArxivEntry objects.
    """
    entries: List[ArxivEntry] = []

    for e in feed.entries:
        # arxiv_id is the last part of the id or link, e.g. '2507.07611v1'
        raw_id = e.get("id", "") or e.get("link", "")
        arxiv_id = raw_id.split("/")[-1]

        title = clean_whitespace(e.get("title", ""))

        authors = [a.get("name", "").strip() for a in e.get("authors", [])]

        # Use 'published' if available, otherwise fall back to now
        published_str = e.get("published", "")
        try:
            published_dt = datetime.strptime(published_str, "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            published_dt = datetime.utcnow()
        year = published_dt.year

        primary_cat = None
        if hasattr(e, "arxiv_primary_category"):
            primary_cat = e.arxiv_primary_category.get("term", None)

        journal_ref = getattr(e, "arxiv_journal_ref", None)
        doi = getattr(e, "arxiv_doi", None)

        url = e.get("link", f"https://arxiv.org/abs/{arxiv_id}")

        entries.append(
            ArxivEntry(
                arxiv_id=arxiv_id,
                title=title,
                authors=authors,
                year=year,
                published=published_dt,
                primary_category=primary_cat,
                journal_ref=journal_ref,
                doi=doi,
                url=url,
            )
        )

    # Sort entries by published date (newest first)
    entries.sort(key=lambda x: x.published, reverse=True)
    return entries


def arxiv_entry_to_bibtex(entry: ArxivEntry) -> str:
    """
    Convert a single ArxivEntry into a BibTeX entry string.

    We use @article if a journal_ref or DOI is present, otherwise @misc.
    """
    key = make_bibtex_key(entry)
    has_journal = bool(entry.journal_ref)
    has_doi = bool(entry.doi)

    # Decide entry type
    entry_type = "article" if (has_journal or has_doi) else "misc"

    lines = [f"@{entry_type}{{{key},"]

    # Required-ish fields
    lines.append(f"  title        = {{{entry.title}}},")
    lines.append(f"  author       = {{{format_authors_bibtex(entry.authors)}}},")
    lines.append(f"  year         = {{{entry.year}}},")

    # arXiv-specific fields
    lines.append(f"  eprint       = {{{entry.arxiv_id}}},")
    lines.append("  archivePrefix = {arXiv},")

    if entry.primary_category:
        lines.append(f"  primaryClass = {{{entry.primary_category}}},")

    lines.append(f"  url          = {{{entry.url}}},")

    # Journal and DOI information, if available
    if entry.journal_ref:
        lines.append(f"  journal      = {{{entry.journal_ref}}},")

    if entry.doi:
        lines.append(f"  doi          = {{{entry.doi}}},")

    # Extra fields that PRISM can use for filtering/selection
    lines.append("  selected     = {false},")
    lines.append("  preview      = {false},")
    lines.append("  description  = {},")
    lines.append("}\n")

    return "\n".join(lines)


def write_bibtex_file(entries: List[ArxivEntry], output_path: str, source_url: str) -> None:
    """
    Write all entries to a BibTeX file, with a header indicating that the file is auto-generated.
    """
    header = textwrap.dedent(
        f"""\
        % This file is auto-generated by scripts/update_publications_from_arxiv.py
        % Do not edit manually; your changes will be overwritten.
        % Source: {source_url}
        %
        """
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)
        for entry in entries:
            bib = arxiv_entry_to_bibtex(entry)
            f.write(bib)
            f.write("\n")

    print(f"Wrote {len(entries)} BibTeX entries to {output_path}")


# ------------- Main entry point -------------

def main() -> None:
    atom_url = author_profile_to_atom2_url(AUTHOR_PROFILE_URL)
    print(f"Fetching arXiv Atom2 feed from: {atom_url}")

    feed = fetch_atom_feed(atom_url)
    entries = parse_entries(feed)

    print(f"Parsed {len(entries)} entries from the feed")

    write_bibtex_file(entries, OUTPUT_BIB, AUTHOR_PROFILE_URL)


if __name__ == "__main__":
    main()
