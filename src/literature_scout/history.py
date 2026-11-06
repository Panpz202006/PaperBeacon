"""Select unpublished-to-the-reader historical records from the local topic library."""
from datetime import date, timedelta
import hashlib
import json
from .dedup import deduplicate
from .models import Paper
from .monitor import identity_tokens
from .ranking import ranking_text


def historical_shortlists(configs, folder, today, reported, ranker):
    cutoff = today - timedelta(days=6)
    excluded = set(reported)
    scopes = {}
    # Honor every topic's sent identities, not only the combined email history.
    for slug, cfg in configs:
        path = folder / slug / 'daily-state.json'
        if not path.exists():
            continue
        state = json.loads(path.read_text(encoding='utf-8'))
        scope = {key: cfg[key] for key in ('venues', 'include_arxiv', 'sources', 'queries', 'venue_aliases')}
        expected = hashlib.sha256(json.dumps([cfg['topic'], scope], sort_keys=True).encode()).hexdigest()
        if state.get('scope') != expected:
            continue
        scopes[slug] = state
        excluded.update(state.get('reported', []))
    prepared, issues = [], []
    for slug, cfg in configs:
        if slug not in scopes:
            continue
        directory = folder / slug
        records = []
        files = [directory / 'baseline-candidates.json', directory / 'baseline.json']
        files += sorted(directory.glob('candidates-*.json'))
        for path in files:
            if not path.exists():
                continue
            try:
                rows = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(rows, list):
                    raise ValueError('Expected a paper list')
                records.extend(Paper.from_dict(row) for row in rows if isinstance(row, dict) and row.get('title'))
            except (OSError, ValueError, TypeError) as exc:
                issues.append(f'{slug}: could not read historical file {path.name} ({type(exc).__name__})')
        eligible = []
        for paper in deduplicate(records):
            if identity_tokens(paper) & excluded:
                continue
            try:
                old = date.fromisoformat(paper.published[:10]) < cutoff
            except (ValueError, TypeError):
                old = type(paper.year) is int and paper.year < cutoff.year
            if old:
                eligible.append(paper)
        ranked = ranker(eligible, ranking_text(cfg, cfg['topic']), cfg['llm_model'])[:5]
        if ranked:
            prepared.append((slug, cfg, {'papers': [p.to_dict() for p in ranked],
                'coverage_warnings': [], 'selection_mode': 'historical',
                'history_files': [str(path) for path in files if path.exists()]}))
    return prepared, issues
