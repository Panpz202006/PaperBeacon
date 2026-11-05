"""Simple JSON configuration for no-dependency deployment."""
from __future__ import annotations
import json
from pathlib import Path

DEFAULT = {
    'name': 'Literature Scout',
    'recovery_dir': '',
    'retrieval_policy': 'strict',
    'openalex_anonymous_fallback': False,
    'timezone': 'Asia/Shanghai',
    'send_time': '07:30',
    'llm_model': 'gpt-6-astra',
    'ranking_method': 'keyword',
    'ranking_keywords': [],
    'topic': '',
    'abstract_file': '',
    'since': 2024,
    'venues': ['CVPR', 'ICCV', 'NeurIPS', 'ICLR', 'MICCAI', 'IEEE TMI', 'Medical Image Analysis'],
    'include_arxiv': True,
    'sources': ['openalex', 'semantic_scholar', 'dblp', 'arxiv'],
    'per_source_per_query': 20,
    'max_queries': 3,
    'queries': [],
    'max_papers': 40,
    'openalex_semantic': False,
    'venue_aliases': {}
}

def load_config(path: str | Path) -> dict:
    filepath = Path(path).resolve()
    with open(filepath, encoding='utf-8') as f:
        user = json.load(f)
    unknown = set(user) - set(DEFAULT)
    if unknown:
        raise ValueError(f'Unknown config fields: {sorted(unknown)}')
    out = {**DEFAULT, **user}
    if out['abstract_file']:
        af = Path(out['abstract_file'])
        if not af.is_absolute():
            af = filepath.parent / af
        out['abstract_file'] = str(af)
    if not isinstance(out['venues'], list) or not isinstance(out['sources'], list):
        raise ValueError('venues and sources must be lists')
    if not isinstance(out['since'], int) or out['since'] < 1900:
        raise ValueError('since must be a four-digit year')
    if not isinstance(out['per_source_per_query'], int) or out['per_source_per_query'] < 1:
        raise ValueError('per_source_per_query must be >= 1')
    from datetime import time
    from zoneinfo import ZoneInfo
    ZoneInfo(out['timezone'])
    time.fromisoformat(out['send_time'])
    if len(out['send_time']) != 5:
        raise ValueError('send_time must be HH:MM')
    if out['ranking_method'] not in ('keyword', 'gpt'):
        raise ValueError('ranking_method must be keyword or gpt')
    if not isinstance(out['ranking_keywords'], list) or any(not isinstance(x, str) for x in out['ranking_keywords']):
        raise ValueError('ranking_keywords must be a list of strings')
    if out['retrieval_policy'] not in ('strict', 'available'):
        raise ValueError('retrieval_policy must be strict or available')
    return out
