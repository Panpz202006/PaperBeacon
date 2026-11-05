"""Data model, explicit provenance, and serialization."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any
import re
import unicodedata


def normalize_text(value: str) -> str:
    text = unicodedata.normalize('NFKC', value or '').casefold()
    return re.sub(r'\s+', ' ', re.sub(r'[^\w]+', ' ', text)).strip()


def normalize_doi(doi: str) -> str:
    value = (doi or '').strip().lower()
    value = re.sub(r'^https?://(dx\.)?doi\.org/', '', value)
    return re.sub(r'^doi:\s*', '', value).strip().rstrip('.,')


def normalize_arxiv(arxiv_id: str) -> str:
    value = (arxiv_id or '').strip()
    value = re.sub(r'^https?://(www\.)?arxiv\.org/(abs|pdf)/', '', value)
    value = re.sub(r'\.pdf$', '', value)
    return re.sub(r'v\d+$', '', value)


@dataclass
class Paper:
    title: str
    year: int | None = None
    abstract: str = ''
    venue_raw: str = ''
    venue_canonical: str = ''
    publication_type: str = 'unknown'   # journal / conference / preprint / unknown
    doi: str = ''
    arxiv_id: str = ''
    url: str = ''
    pdf_url: str = ''
    authors: list[str] = field(default_factory=list)
    author_affiliations: dict[str, list[str]] = field(default_factory=dict)
    author_roles: dict[str, list[str]] = field(default_factory=dict)
    affiliation_sources: list[str] = field(default_factory=list)
    published: str = ''
    citations: int | None = None
    identifiers: dict[str, str] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    score: float = 0.0
    matched_terms: list[str] = field(default_factory=list)
    # This is metadata classification, NOT peer-review validation.
    venue_evidence: str = 'none'   # metadata / preprint / none

    def __post_init__(self) -> None:
        self.doi = normalize_doi(self.doi)
        self.arxiv_id = normalize_arxiv(self.arxiv_id)
        self.title = ' '.join(self.title.split())

    @property
    def key(self) -> str:
        if self.doi:
            return 'doi:' + self.doi
        if self.arxiv_id:
            return 'arxiv:' + self.arxiv_id.lower()
        return 'title:' + normalize_text(self.title) + ':' + str(self.year or '')

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> 'Paper':
        allowed = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in obj.items() if k in allowed})
