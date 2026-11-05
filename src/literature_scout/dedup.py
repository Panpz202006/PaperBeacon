"""DOI/arXiv/exact normalized-title deduplication, preserving provenance."""
from __future__ import annotations
from .models import Paper, normalize_text


def identity_keys(p: Paper) -> set[str]:
    keys = set()
    if p.doi:
        keys.add('doi:' + p.doi)
    if p.arxiv_id:
        keys.add('arxiv:' + p.arxiv_id.casefold())
    title = normalize_text(p.title)
    if title:
        keys.add('title:' + title)
    return keys


def combine(group: list[Paper]) -> Paper:
    # Prefer explicit publication venue; then abstract length; then source count.
    def quality(p: Paper):
        is_venue = bool(p.venue_raw and p.venue_raw.lower() not in {'arxiv','arxiv preprint','repository'})
        return (int(is_venue), len(p.abstract), len(p.authors))
    ordered = sorted(group, key=quality, reverse=True)
    p = Paper.from_dict(ordered[0].to_dict())
    for other in ordered[1:]:
        for s in other.sources:
            if s not in p.sources:
                p.sources.append(s)
        for note in other.notes:
            if note not in p.notes:
                p.notes.append(note)
        p.identifiers.update(other.identifiers)
        for field in ('author_affiliations', 'author_roles'):
            target = getattr(p, field)
            for author, values in getattr(other, field).items():
                target[author] = list(dict.fromkeys(target.get(author, []) + values))
        p.affiliation_sources = list(dict.fromkeys(p.affiliation_sources + other.affiliation_sources))
        for attr in ('doi','arxiv_id','abstract','published','url','pdf_url','venue_raw'):
            if not getattr(p, attr) and getattr(other, attr):
                setattr(p, attr, getattr(other, attr))
        if not p.year and other.year:
            p.year = other.year
        if not p.authors and other.authors:
            p.authors = other.authors
        if p.citations is None or (other.citations is not None and other.citations > p.citations):
            p.citations = other.citations
    return p


def deduplicate(papers: list[Paper]) -> list[Paper]:
    """Merge only when robust identifiers match or normalized titles are exact with near year."""
    n = len(papers)
    parent = list(range(n))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i, j):
        parent[root(j)] = root(i)

    key_to_idxs = {}
    for i, p in enumerate(papers):
        for key in identity_keys(p):
            for other_i in key_to_idxs.get(key, []):
                other = papers[other_i]
                if key.startswith('title:') and p.year and other.year and abs(p.year - other.year) > 1:
                    continue
                join(i, other_i)
            key_to_idxs.setdefault(key, []).append(i)
    grouped = {}
    for i, p in enumerate(papers):
        grouped.setdefault(root(i), []).append(p)
    return [combine(g) for g in grouped.values()]
