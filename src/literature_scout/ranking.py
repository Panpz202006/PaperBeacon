"""Transparent lexical relevance and query planning. Scores are not novelty judgments."""
from __future__ import annotations
from collections import Counter
from datetime import date
import re
from .models import Paper

STOP = set('''a an the and or but if we our ours this that these those then can could do does did to for of with without on in at by from as is are was were be been being via using use into over under than not both also which where while there their its it new novel state based proposed proposing propose study investigate method methods framework models model network neural image images approach approaches task tasks paper results data show demonstrates demonstrate efficient robust comprehensive evaluation evaluate experiments results achieve propose learning deep'''.split())


def terms(s: str) -> list[str]:
    return [t for t in re.findall(r'[a-z][a-z0-9-]{2,}', s.casefold()) if t not in STOP]


def plan_queries(text: str, *, max_queries: int = 3, overrides: list[str] | None = None) -> list[str]:
    if overrides:
        return list(dict.fromkeys(q.strip() for q in overrides if q.strip()))[:max_queries]
    words = terms(text)
    if not words:
        return [text.strip()[:120]]
    # Prefer informative terms from the first sentence, plus high-frequency terms.
    first_sentence = re.split(r'(?<=[.!?])\s+', text.strip(), maxsplit=1)[0]
    head = list(dict.fromkeys(terms(first_sentence)))[:8]
    freq = Counter(words)
    common = [w for w, _ in sorted(freq.items(), key=lambda x: (-x[1], -len(x[0]), x[0]))][:10]
    longphrase = list(dict.fromkeys(words))[:8]
    queries = [' '.join(head[:7]), ' '.join(common[:6]), ' '.join(longphrase[:5])]
    return list(dict.fromkeys(q for q in queries if q))[:max_queries]


def score_papers(papers: list[Paper], research_text: str, current_year: int | None = None) -> list[Paper]:
    desired = set(terms(research_text))
    this_year = current_year or date.today().year
    for p in papers:
        title = set(terms(p.title))
        abstract = set(terms(p.abstract))
        overlap = desired & (title | abstract)
        p.matched_terms = sorted(overlap)
        denom = max(1, len(desired))
        title_cov = len(desired & title) / denom
        abs_cov = len(desired & abstract) / denom
        year_bonus = max(0.0, 1.0 - max(0, this_year - p.year) / 8.0) if p.year else 0.0
        p.score = round(100 * (0.60 * title_cov + 0.32 * abs_cov + 0.08 * year_bonus), 2)
    return sorted(papers, key=lambda p: (p.score, p.year or 0), reverse=True)


def keyword_rank(papers: list[Paper], research_text: str, model=None, *, baseline=False) -> list[Paper]:
    """Local title/abstract relevance only; dates break ties, never create relevance."""
    desired = set(terms(research_text))
    if not desired:
        return []
    ranked = []
    for paper in papers:
        title_matches = desired & set(terms(paper.title))
        abstract_matches = desired & set(terms(paper.abstract))
        if not title_matches and not abstract_matches:
            continue
        paper.matched_terms = sorted(title_matches | abstract_matches)
        paper.score = round(100 * (0.7 * len(title_matches) + 0.3 * len(abstract_matches)) / len(desired), 3)
        ranked.append(paper)
    ranked.sort(key=lambda p: (-p.score, -(int(p.published[:10].replace('-', ''))
                if len(p.published) >= 10 and p.published[:10].replace('-', '').isdigit() else 0), p.key))
    return ranked if baseline else ranked[:5]


def daily_ranker(config):
    if config.get('ranking_method', 'keyword') == 'keyword':
        return keyword_rank
    from .llm import rank_papers
    return rank_papers


def ranking_text(config, research_text):
    return research_text + ' ' + ' '.join(config.get('ranking_keywords', []))
