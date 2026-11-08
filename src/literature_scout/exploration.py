"""Enumerate indexed conference records before local topic matching."""
from datetime import datetime
from email.utils import format_datetime, make_msgid, getaddresses
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .daily import send_email
from .dedup import deduplicate
from .http_client import HttpClient, RateLimitError, AuthenticationError
from .models import Paper
from .pipeline import ScanResult
from .ranking import terms
from .matching import rank_exploration, resolve_topic_weights
from .reporting import export_result
from .sources.dblp import API, parse_response
from .sources.proceedings import Proceedings
from .venues import gate

STREAMS = {'NeurIPS': 'nips', 'ICML': 'icml', 'ICLR': 'iclr', 'AAAI': 'aaai',
           'ACM MM': 'mm', 'CVPR': 'cvpr', 'IJCAI': 'ijcai'}


def paper_list(papers):
    """Reader-facing exploration output; diagnostics remain in separate files."""
    rows = ['Paper name\tYear\tVenue']
    rows.extend(f'{p.title}\t{p.year or "Unknown"}\t{p.venue_canonical or p.venue_raw or "Unknown"}'
                for p in papers)
    return '\n'.join(rows) + '\n'


def enumerate_year(client, venue, year):
    query = f'stream:conf/{STREAMS[venue]}: year:{year}:'
    offset, total = 0, None
    papers, seen = [], set()
    while total is None or offset < total:
        data = client.json(API, {'q': query, 'format': 'json', 'h': 1000, 'f': offset, 'c': 0})
        hits = data['result']['hits']
        count = int(hits['@total'])
        if total is not None and count != total:
            raise RuntimeError('Index changed during pagination; retry collection')
        total = count
        rows = hits.get('hit') or []
        if isinstance(rows, dict):
            rows = [rows]
        if not rows and offset < total:
            raise RuntimeError(f'Pagination stopped at {offset} of {total}')
        for row in rows:
            key = (row.get('info') or {}).get('key') or row.get('@id')
            if key is None or key in seen:
                raise RuntimeError('Missing or repeated record identity during pagination')
            seen.add(key)
        papers.extend(parse_response(data))
        offset += len(rows)
        if offset >= total:
            break
    return papers, {'venue': venue, 'year': year, 'indexed_total': total,
                    'retrieved': offset, 'pagination_complete': True, 'query': query}


def explore(text, folder, *, since, until, fixture=None, email_to=None, client=None, sender=send_email,
            venues=None, top=None, match='any', from_run=None, weights=None):
    if not text.strip():
        raise ValueError('Provide nonempty keywords or a research description')
    if top is not None and (not isinstance(top, int) or top < 1):
        raise ValueError('top must be a positive integer')
    if not 1900 <= since <= until <= 9999:
        raise ValueError('Use an inclusive year range: 1900 <= since <= until <= 9999')
    if not terms(text):
        raise ValueError('Provide informative research keywords')
    if match not in {'any', 'all'}:
        raise ValueError('match must be any or all')
    topic_weights = resolve_topic_weights(text, weights)
    if from_run and fixture:
        raise ValueError('Choose a saved run or an offline fixture, not both')
    if email_to:
        addresses = getaddresses([email_to])
        if not addresses or any('@' not in address or '\n' in address or '\r' in address for _, address in addresses):
            raise ValueError('Provide a valid email recipient')
        email_to = ', '.join(address for _, address in addresses)
    cfg = load_config(Path(__file__).resolve().parents[2] / 'config/area_search.json')
    cfg.update(since=since, until=until)
    if venues is not None:
        if isinstance(venues, str):
            venues = [venues]
        venues = [part.strip() for value in venues for part in value.split(',') if part.strip()]
        selected = list(dict.fromkeys('NeurIPS' if v == 'NIPS' else v for v in venues))
        if not selected or any(v not in STREAMS for v in selected):
            raise ValueError('Choose at least one supported conference venue')
        cfg['venues'] = selected
    records, coverage, warnings = [], [], []
    if from_run:
        saved = Path(from_run)
        previous = json.loads((saved / 'manifest.json').read_text(encoding='utf-8'))
        prior_config = previous['config']
        if venues is None:
            cfg['venues'] = prior_config['venues']
        if not set(cfg['venues']) <= set(prior_config['venues']):
            raise ValueError('Requested venues were not included in the saved run')
        if since < prior_config['since'] or until > prior_config['until']:
            raise ValueError('Requested year range exceeds the saved run')
        records = [Paper.from_dict(p) for p in json.loads((saved / 'venue-corpus.json').read_text(encoding='utf-8'))]
        coverage = [entry for entry in json.loads((saved / 'coverage.json').read_text(encoding='utf-8'))
                    if entry['venue'] in cfg['venues'] and since <= entry['year'] <= until]
        covered = {(c['venue'], c['year']) for c in coverage}
        if not previous.get('fixture_mode'):
            coverage.extend({'venue': venue, 'year': year, 'pagination_complete': False,
                             'error': 'No coverage recorded in the saved run'}
                            for venue in cfg['venues'] for year in range(since, until + 1)
                            if (venue, year) not in covered)
        warnings = [f'{c["venue"]} {c["year"]}: saved collection incomplete: {c.get("error", "unknown")}'
                    for c in coverage if not c['pagination_complete']]
        if previous.get('fixture_mode'):
            warnings.append('OFFLINE FIXTURE: saved corpus contains synthetic records.')
        cfg.update(source_run=str(saved.resolve()), source_run_utc=previous['run_utc'])
    elif fixture:
        records = [Paper.from_dict(p) for p in json.loads(Path(fixture).read_text())['papers']]
        warnings.append('OFFLINE FIXTURE: synthetic records; live venue coverage was not checked.')
    else:
        client = client or HttpClient(defer_rate_limits=True)
        proceedings = Proceedings(client)
        dblp_failure = None
        unavailable_sources = {}
        for venue in cfg['venues']:
            for year in range(since, until + 1):
                try:
                    found = []
                    if dblp_failure is None:
                        try:
                            found, status = enumerate_year(client, venue, year)
                        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
                            dblp_failure = str(exc)
                    if not found:
                        source = 'crossref' if venue in {'AAAI', 'ACM MM'} else venue
                        if source in unavailable_sources:
                            raise RuntimeError('Source deferred after access/rate-limit failure: ' + unavailable_sources[source])
                        try:
                            found, status = proceedings.enumerate_year(venue, year)
                        except (RateLimitError, AuthenticationError) as exc:
                            unavailable_sources[source] = str(exc)
                            raise
                        status['fallback_reason'] = dblp_failure or 'No DBLP records returned for this venue/year'
                    records.extend(found)
                    coverage.append(status)
                    if not found:
                        warnings.append(f'{venue} {year}: no indexed records; proceedings may be unavailable.')
                except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
                    coverage.append({'venue': venue, 'year': year, 'pagination_complete': False,
                                     'error': str(exc), 'dblp_error': dblp_failure})
                    warnings.append(f'{venue} {year}: collection incomplete: {exc}')
    eligible = []
    for paper in deduplicate(records):
        if paper.year is not None and since <= paper.year <= until:
            matched = gate(paper, venues=cfg['venues'], include_arxiv=False)
            if matched:
                eligible.append(matched)
    ranked, match_details, topics = rank_exploration(eligible, text, match=match, weights=topic_weights)
    cfg.update(matching_method='local_topic_bm25_v2', match=match, matching_topics=topics, topic_weights=topic_weights)
    matched = [p for p in ranked if p.matched_terms]
    matching_count = len(matched)
    if top is not None:
        matched = matched[:top]
        cfg['top'] = top
    warnings.append('Indexed proceedings metadata is not independent acceptance verification. '
                    'Local topic/word matching can miss semantic matches; title-only records have limited evidence. '
                    'Complete pagination does not establish complete official proceedings coverage.')
    result = ScanResult(cfg, text, [c['query'] for c in coverage if 'query' in c], matched, warnings,
                        {'retrieved_records': len(records), 'eligible_records': len(eligible),
                         'matching_records': matching_count, 'selected_records': len(matched),
                         'venue_coverage': {venue: {
                             'completed_years': [c['year'] for c in coverage if c['venue'] == venue and c['pagination_complete']],
                             'failed_years': [c['year'] for c in coverage if c['venue'] == venue and not c['pagination_complete']],
                             'retrieved_records': sum(c.get('retrieved', 0) for c in coverage if c['venue'] == venue),
                             'selected_records': sum(p.venue_canonical == venue for p in matched)}
                             for venue in cfg['venues']}},
                        fixture_mode=bool(fixture or (from_run and previous.get('fixture_mode'))))
    folder = Path(folder)
    completed_at = datetime.now(ZoneInfo('Asia/Shanghai'))
    report_path = folder / f'report-{completed_at:%Y%m%d-%H%M%S-%f}.txt'
    cfg['report_file'] = str(report_path)
    artifacts = export_result(result, folder)
    (folder / 'coverage.json').write_text(json.dumps(coverage, indent=2), encoding='utf-8')
    (folder / 'matching.json').write_text(json.dumps({
        'method': cfg['matching_method'], 'topics': topics, 'match': match, 'weights': topic_weights,
        'papers': [{'key': p.key, 'title': p.title, **match_details[p.key]} for p in matched]},
        indent=2, ensure_ascii=False), encoding='utf-8')
    (folder / 'venue-corpus.json').write_text(json.dumps([p.to_dict() for p in ranked], indent=2,
                                                     ensure_ascii=False), encoding='utf-8')
    body = paper_list(matched)
    if not matched:
        incomplete = not result.fixture_mode and (not coverage or any(not c['pagination_complete'] for c in coverage))
        message = ('Search incomplete: retrieval failed. No conclusion about matching papers can be drawn.'
                   if incomplete else 'No keyword matches in the retrieved proceedings for this year range; semantic matches may exist.')
        body += '\n' + message + '\n'
    (folder / 'report.txt').write_text(body, encoding='utf-8')
    (folder / 'report.md').write_text(body, encoding='utf-8')
    report_path.write_text(body, encoding='utf-8')
    if email_to:
        sender({'to': email_to, 'subject': f'PaperBeacon exploration | {since}–{until} | {len(matched)} papers',
                'body': body, 'message_id': make_msgid(domain='literature-scout.local'),
                'date_header': format_datetime(datetime.now().astimezone()),
                'attachments': [str(report_path), artifacts['papers.json'], str(folder / 'coverage.json')]})
    return result
