"""Reports, machine-readable export and BibTeX. No fabricated bibliographic fields."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import json
import re
from .models import Paper
from .pipeline import ScanResult


def md_escape(s: str) -> str:
    return (s or '').replace('|', '\\|').replace('\n', ' ')


def make_report(result: ScanResult) -> str:
    cfg = result.config
    title = cfg.get('name') or 'Literature Scout'
    lines = [f'# {title} — Literature Discovery', '', f'**Run (UTC):** {result.run_utc}',
             f'**Mode:** {"OFFLINE DEMONSTRATION — SYNTHETIC FIXTURES" if result.fixture_mode else "LIVE API SEARCH"}',
             f'**Since:** {cfg["since"]}',
             f'**Target venues:** {", ".join(cfg["venues"]) or "none"}',
             f'**arXiv allowed:** {cfg["include_arxiv"]}',
             f'**Retained records:** {len(result.papers)}', '',
             '## Research question / abstract', '', result.research_text.strip(), '',
             '## Search queries', '']
    lines += [f'- `{q}`' for q in result.queries]
    lines += ['', '## Retrieval statistics', '']
    lines += [f'- {k}: {v}' for k, v in result.counts.items()]
    lines += ['', '## Ranked papers', '',
              '| # | Paper | Year | Venue (metadata) | Textual relevance | Evidence |',
              '|---:|---|---:|---|---:|---|']
    for i, p in enumerate(result.papers, 1):
        link = f'[{md_escape(p.title)}]({p.url})' if p.url.startswith('http') else md_escape(p.title)
        lines.append(f'| {i} | {link} | {p.year or "?"} | {md_escape(p.venue_canonical)} | {p.score:.1f} | {p.venue_evidence} |')
    lines += ['', '## Paper-level evidence cards', '']
    for i, p in enumerate(result.papers, 1):
        lines += [f'### {i}. {p.title}', '',
                  f'- **Authors:** {", ".join(p.authors) if p.authors else "Not available"}',
                  f'- **Date:** {p.published or p.year or "Unknown"}',
                  f'- **Venue field:** {p.venue_raw or "Unknown"}',
                  f'- **Selected venue:** {p.venue_canonical}',
                  f'- **Venue evidence:** {p.venue_evidence} (metadata only; not independently peer-review verified)',
                  f'- **DOI:** {p.doi or "Not available"}',
                  f'- **arXiv:** {p.arxiv_id or "Not available"}',
                  f'- **Source adapters:** {", ".join(p.sources)}',
                  f'- **URL:** {p.url or "Not available"}',
                  f'- **PDF:** {p.pdf_url or "Not available"}',
                  f'- **Keyword overlap:** {", ".join(p.matched_terms) if p.matched_terms else "None"}',
                  f'- **Abstract:** {p.abstract.strip() or "Not available from the consulted metadata"}', '']
        if p.notes:
            lines += ['- **Notes:** ' + '; '.join(p.notes), '']
    if result.warnings:
        lines += ['## Warnings / incomplete coverage', '']
        lines += [f'- {w}' for w in result.warnings]
        lines += ['']
    lines += ['## How to interpret these results', '',
              '- Relevance is a reproducible lexical overlap heuristic, **not** a novelty or scientific-quality score.',
              '- Venue fields come from indexed metadata and **do not prove acceptance**; confirm closest papers against official proceedings.',
              '- arXiv is a preprint source. An arXiv journal-reference note is not independently validated.',
              '- This starter analyzes metadata abstracts, **not** entire PDFs; inspect full methods and equations before originality judgments.',
              '- Missing papers are possible because of query formulation, indexing lag, search caps, or API failures.',
              '- Assess claims such as “first” or “no prior work” only after further manual/full-text verification.', '']
    return '\n'.join(lines)


def bib_entry(p: Paper, index: int) -> str:
    # Avoid claiming peer-reviewed when our sole evidence is metadata.
    category = 'misc' if p.venue_canonical == 'arXiv' else ('article' if 'journal' in p.publication_type.lower() else 'misc')
    key = f'scout{p.year or "nd"}_{index}'
    fields = [('title', p.title), ('author', ' and '.join(p.authors)),
              ('year', str(p.year or '')), ('howpublished', p.venue_raw),
              ('doi', p.doi), ('url', p.url)]
    def esc(v):
        return v.replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')
    lines = [f'@{category}{{{key},']
    lines += [f'  {k} = {{{esc(v)}}},' for k, v in fields if v]
    return '\n'.join(lines) + '\n}\n'


def export_result(result: ScanResult, folder: Path) -> dict[str, str]:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'report.md').write_text(make_report(result), encoding='utf-8')
    (folder / 'papers.json').write_text(json.dumps([p.to_dict() for p in result.papers],
                                                   indent=2, ensure_ascii=False), encoding='utf-8')
    from .daily import plain_report
    (folder / 'report.txt').write_text(plain_report(result.config['name'], result.papers), encoding='utf-8')
    (folder / 'papers.bib').write_text('\n'.join(bib_entry(p, i) for i,p in enumerate(result.papers, 1)),
                                       encoding='utf-8')
    manifest = {'run_utc': result.run_utc, 'fixture_mode': result.fixture_mode,
                'config': result.config, 'queries': result.queries,
                'counts': result.counts, 'warnings': result.warnings,
                'research_text': result.research_text}
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    return {name: str(folder / name) for name in ('report.md','papers.json','report.txt','papers.bib','manifest.json')}
