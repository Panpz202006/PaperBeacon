"""Source orchestration, verification gates, and deterministic ranking."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import logging
from .config import load_config
from .models import Paper
from .http_client import HttpClient, RateLimitError, AuthenticationError, ResponseFormatError
from .ranking import plan_queries, score_papers
from .dedup import deduplicate
from .venues import gate
from .sources import openalex, semantic_scholar, dblp, arxiv

SOURCES = {'openalex': openalex, 'semantic_scholar': semantic_scholar, 'dblp': dblp, 'arxiv': arxiv}
LOG = logging.getLogger(__name__)

@dataclass
class ScanResult:
    config: dict
    research_text: str
    queries: list[str]
    papers: list[Paper]
    warnings: list[str] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    run_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    fixture_mode: bool = False


def run_scan(config: dict, research_text: str, *, client: HttpClient | None = None,
             offline_fixture: str | None = None) -> ScanResult:
    client = client or HttpClient(defer_rate_limits=bool(config.get('recovery_dir')))
    queries = plan_queries(research_text, max_queries=config['max_queries'], overrides=config.get('queries'))
    collected: list[Paper] = []
    warnings: list[str] = []
    counts = {'successful_queries': 0, 'cached_queries': 0}
    rate_limited = set()
    if offline_fixture:
        with open(offline_fixture, encoding='utf-8') as f:
            data = json.load(f)
        collected = [Paper.from_dict(x) for x in data['papers']]
        counts['offline_fixture'] = len(collected)
    else:
        for source_name in config['sources']:
            if source_name not in SOURCES:
                warnings.append(f'Unrecognized source: {source_name}')
                continue
            adapter = SOURCES[source_name]
            if config.get('recovery_dir'):
                from .source_recovery import recover_source
                found, issues, fresh, cached = recover_source(config, source_name, queries, adapter, client)
                collected.extend(found)
                warnings.extend(issues)
                counts[source_name] = len(found)
                counts['successful_queries'] += fresh
                counts['cached_queries'] += cached
                if issues:
                    rate_limited.add(source_name)
                for issue in issues:
                    LOG.warning('%s', issue)
                continue
            total = 0
            for query in queries:
                try:
                    date_options = ({'date_start': config['_date_start'], 'date_end': config['_date_end']}
                                    if config.get('_date_start') and source_name in {'openalex', 'arxiv'} else {})
                    found = adapter.search(query, **date_options, since=config['since'],
                                           limit=config['per_source_per_query'], client=client)
                    collected.extend(found)
                    total += len(found)
                    counts['successful_queries'] += 1
                except (RateLimitError, AuthenticationError, ResponseFormatError) as exc:
                    rate_limited.add(source_name)
                    warning = f'{source_name}: {exc} Skipping remaining queries for this source.'
                    warnings.append(warning)
                    LOG.warning('%s', warning)
                    break
                except (RuntimeError, ValueError, OSError, KeyError) as exc:
                    warning = f'{source_name}: query {query!r} failed: {exc}'
                    warnings.append(warning)
                    LOG.warning('%s', warning)
            counts[source_name] = total
        if (config.get('openalex_semantic') and 'openalex' in config['sources']
                and 'openalex' not in rate_limited):
            try:
                found = openalex.semantic_search(research_text, since=config['since'],
                    limit=config['per_source_per_query'], client=client)
                collected.extend(found)
                counts['openalex_semantic'] = len(found)
            except (RuntimeError, ValueError, OSError, KeyError) as exc:
                warnings.append(f'openalex_semantic failed: {exc}')
    merged = deduplicate(collected)
    allowed = []
    for p in merged:
        if p.year is None or p.year < config['since']:
            continue
        matched = gate(p, venues=config['venues'], include_arxiv=config['include_arxiv'],
                       aliases=config.get('venue_aliases'))
        if matched:
            allowed.append(matched)
    if config.get('_date_start'):
        allowed = [p for p in allowed if len(p.published) >= 10
                   and config['_date_start'] <= p.published[:10] <= config['_date_end']]
    allowed = score_papers(allowed, research_text)
    if not config.get('_date_start'):
        allowed = allowed[:config['max_papers']]
    counts.update({'retrieved_records': len(collected), 'after_dedup': len(merged),
                   'after_venue_filter': len(allowed)})
    if not collected and not config.get('_date_start'):
        warnings.append('No records returned. Check API access, search terms, and rate limits.')
    return ScanResult(config=config, research_text=research_text, queries=queries, papers=allowed,
                      warnings=warnings, counts=counts, fixture_mode=bool(offline_fixture))
