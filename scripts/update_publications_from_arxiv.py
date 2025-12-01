#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Fetch publications from an arXiv author profile page and generate a BibTeX file
for PRISM.

- Uses the arXiv author profile (e.g. https://arxiv.org/a/wang_t_9.html)
- Converts to the Atom2 feed (https://arxiv.org/a/... .atom2)
- Parses entries and writes content/publications.bib

The generated BibTeX entries include:
    title, author, year, eprint, url, journal, doi, abstract, description,
    archivePrefix, primaryClass, selected, preview, keywords.
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


# --------- Configuration ---------

AUTHOR_PROFILE_URL = "https://arxiv.org/a/wang_t_9.html"
OUTPUT_BIB = os.path.join("content", "publications.bib")
MAX_ENTRIES = 500  # just a safety cap


# --------- Data structures ---------

@dataclass
class ArxivEntry:
    arxiv_id: str
    title: str
    authors: List[str]
    year: int
    published: datetime
    updated: datetime
    primary_category: Optional[str]
    journal_ref: Optional[str]
    doi: Optional[str]
    url: str
    abstract: Optional[str] = None


# --------- Helpers ---------

def author_profile_to_atom2_url(profile_url: str) -> str:
    """
    Convert an arXiv author profile HTML URL to the Atom2 feed URL.

    Example:
        https://arxiv.org/a/wang_t_9.html -> https://arxiv.org/a/wang_t_9.atom2
    """
    parsed = urlparse(profile_url)
    slug = os.path.basename(parsed.path)
    if slug.endswith(".html"):
        slug = slug[:-5]
    return f"https://arxiv.org/a/{slug}.atom2"


def clean_whitespace(text: str) -> str:
    """Normalize and collapse whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def extract_year_from_journal_ref(journal_ref: str) -> Optional[int]:
    """
    Try to extract a 4-digit year from a journal reference string, e.g.:

        "Phys. Rev. B 100, 085127 (2019)" -> 2019
    """
    if not journal_ref:
        return None
    # Look for (...) with 4 digits inside, or a standalone 4-digit year
    m = re.search(r"\((\d{4})\)", journal_ref)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(19|20)\d{2}\b", journal_ref)
    if m:
        return int(m.group(0))
    return None


def format_authors_bibtex(authors: List[str]) -> str:
    """
    Format authors for BibTeX.

    We keep the names as given by arXiv and join them with ' and ',
    which is what BibTeX expects.
    """
    return " and ".join(authors)


def first_sentence(text: str) -> str:
    """
    Take the first sentence of a text as a short description.

    This is a very simple splitter and does not try to be linguistically perfect.
    """
    text = clean_whitespace(text)
    if not text:
        return ""
    # Split on period, exclamation or question mark
    parts = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
    return parts[0]


# --------- Fetch and parse Atom feed ---------

def fetch_atom_feed(atom_url: str) -> feedparser.FeedParserDict:
    """Fetch the Atom2 feed and parse it with feedparser."""
    resp = requests.get(atom_url, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.text)
    return feed


def parse_entries(feed: feedparser.FeedParserDict) -> List[ArxivEntry]:
    """
    Convert the Atom feed entries into a list of ArxivEntry objects.

    Year selection logic:
        - If a journal_ref is present and contains a year, use that.
        - Otherwise use the year from 'published'.
    """
    entries: List[ArxivEntry] = []

    for e in feed.entries:
        raw_id = e.get("id", "") or e.get("link", "")
        arxiv_id = raw_id.split("/")[-1]

        title = clean_whitespace(e.get("title", ""))

        authors = [a.get("name", "").strip() for a in e.get("authors", [])]

        # Parse published / updated timestamps
        published_str = e.get("published", "")
        updated_str = e.get("updated", "") or published_str

        def parse_dt(s: str) -> datetime:
            try:
                return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                return datetime.utcnow()

        published_dt = parse_dt(published_str)
        updated_dt = parse_dt(updated_str)

        primary_cat = None
        if hasattr(e, "arxiv_primary_category"):
            primary_cat = e.arxiv_primary_category.get("term", None)

        journal_ref = getattr(e, "arxiv_journal_ref", None)
        doi = getattr(e, "arxiv_doi", None)
        url = e.get("link", f"https://arxiv.org/abs/{arxiv_id}")

        abstract = clean_whitespace(e.get("summary", ""))

        # Decide year: prefer journal_ref year if present, else published year
        year_from_journal = extract_year_from_journal_ref(journal_ref or "")
        if year_from_journal is not None:
            year = year_from_journal
        else:
            year = published_dt.year

        entries.append(
            ArxivEntry(
                arxiv_id=arxiv_id,
                title=title,
                authors=authors,
                year=year,
                published=published_dt,
                updated=updated_dt,
                primary_category=primary_cat,
                journal_ref=journal_ref,
                doi=doi,
                url=url,
                abstract=abstract,
            )
        )

    # Sort by (year, updated) descending to get reverse chronological order
    entries.sort(key=lambda x: (x.year, x.updated), reverse=True)
    return entries


# --------- BibTeX generation ---------

def make_bibtex_key(entry: ArxivEntry) -> str:
    """
    Generate a BibTeX key of the form:
        lastnameYYYYshorttitle
    """
    if entry.authors:
        first_author = entry.authors[0]
        last_name = first_author.split()[-1]
    else:
        last_name = "unknown"

    last_name = re.sub(r"[^A-Za-z]", "", last_name).lower() or "unknown"

    title_slug = re.sub(r"[^A-Za-z0-9]+", " ", entry.title)
    title_slug = title_slug.lower().strip()
    words = title_slug.split()
    short = "".join(words[:4])

    return f"{last_name}{entry.year}{short}"


def arxiv_entry_to_bibtex(entry: ArxivEntry) -> str:
    """
    Convert a single ArxivEntry into a BibTeX entry string.

    We use @article if a journal_ref or DOI is present, otherwise @misc.
    """
    key = make_bibtex_key(entry)
    has_journal = bool(entry.journal_ref)
    has_doi = bool(entry.doi)

    entry_type = "article" if (has_journal or has_doi) else "misc"

    fields = []

    # Core fields
    fields.append(f"  title        = {{{entry.title}}}")
    fields.append(f"  author       = {{{format_authors_bibtex(entry.authors)}}}")
    fields.append(f"  year         = {{{entry.year}}}")

    # arXiv-specific fields
    fields.append(f"  eprint       = {{{entry.arxiv_id}}}")
    fields.append("  archivePrefix = {arXiv}")
    if entry.primary_category:
        fields.append(f"  primaryClass = {{{entry.primary_category}}}")
    fields.append(f"  url          = {{{entry.url}}}")

    # Journal / DOI if available
    if entry.journal_ref:
        fields.append(f"  journal      = {{{entry.journal_ref}}}")
    if entry.doi:
        fields.append(f"  doi          = {{{entry.doi}}}")

    # Abstract and a short description (first sentence)
    if entry.abstract:
        fields.append(f"  abstract     = {{{entry.abstract}}}")
        short_desc = first_sentence(entry.abstract)
        if short_desc:
            fields.append(f"  description  = {{{short_desc}}}")
        else:
            fields.append("  description  = {}")
    else:
        fields.append("  abstract     = {}")
        fields.append("  description  = {}")

    # Extra fields PRISM can use
    fields.append("  selected     = {false}")
    fields.append("  preview      = {}")
    fields.append("  keywords     = {}")

    # Assemble entry
    body = ",\n".join(fields)
    return f"@{entry_type}{{{key},\n{body}\n}}\n"


def write_bibtex_file(entries: List[ArxivEntry], output_path: str, source_url: str) -> None:
    """Write all entries to a BibTeX file with a header."""
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
            f.write(arxiv_entry_to_bibtex(entry))
            f.write("\n")

    print(f"Wrote {len(entries)} BibTeX entries to {output_path}")


# --------- Main ---------

def main() -> None:
    atom_url = author_profile_to_atom2_url(AUTHOR_PROFILE_URL)
    print(f"Fetching arXiv Atom2 feed from: {atom_url}")

    feed = fetch_atom_feed(atom_url)
    entries = parse_entries(feed)

    print(f"Parsed {len(entries)} entries from the feed")

    write_bibtex_file(entries, OUTPUT_BIB, AUTHOR_PROFILE_URL)


if __name__ == "__main__":
    main()
