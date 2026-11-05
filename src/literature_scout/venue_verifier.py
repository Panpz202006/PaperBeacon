"""Independent DOI registry checks; registry agreement is not acceptance proof."""
from datetime import datetime, timezone
from urllib.parse import quote
from .models import normalize_text, normalize_doi
from .http_client import HttpClient


def verify_paper(paper, *, client=None, enabled=True):
    record = {'status': 'unverified', 'acceptance': 'not independently verified',
              'checked_utc': datetime.now(timezone.utc).isoformat(), 'url': '',
              'matched_fields': [], 'conflicts': [], 'registry_metadata': {}}
    if enabled and not paper.doi and paper.arxiv_id:
        return verify_arxiv(paper, client=client)
    if not enabled or not paper.doi:
        record['reason'] = 'Verification disabled' if not enabled else 'No DOI; source metadata only'
        return record
    client = client or HttpClient()
    record['url'] = 'https://api.crossref.org/works/' + quote(paper.doi, safe='')
    try:
        obj = client.json(record['url'])['message']
        title = ' '.join(obj.get('title') or [])
        venue = '; '.join(obj.get('container-title') or [])
        parts = (obj.get('published', {}).get('date-parts') or [[]])[0]
        record['registry_metadata'] = {'doi': obj.get('DOI', ''), 'title': title,
                                       'venue': venue, 'date_parts': parts, 'type': obj.get('type', '')}
        comparisons = {'doi': normalize_doi(obj.get('DOI', '')) == paper.doi,
                       'title': normalize_text(title) == normalize_text(paper.title)}
        if parts and paper.year:
            comparisons['year'] = parts[0] == paper.year
        if len(parts) >= 3 and len(paper.published) >= 10:
            comparisons['publication_date'] = ('-'.join([str(parts[0]), f'{parts[1]:02d}',
                f'{parts[2]:02d}']) == paper.published[:10])
        if venue and paper.venue_raw:
            comparisons['venue'] = normalize_text(venue) == normalize_text(paper.venue_raw)
        for field, matches in comparisons.items():
            record['matched_fields' if matches else 'conflicts'].append(field)
        record['status'] = 'registry_agreement' if not record['conflicts'] else 'conflicting_metadata'
        record['reason'] = 'Crossref registration checked; venue differences may reflect naming variants'
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        record['reason'] = f'Registry check unavailable: {exc}'
    return record



def verify_arxiv(paper, *, client=None):
    from .sources.arxiv import API, parse_feed
    client = client or HttpClient()
    record = {'status': 'unverified', 'acceptance': 'preprint only; acceptance not verified',
              'checked_utc': datetime.now(timezone.utc).isoformat(),
              'url': API + '?id_list=' + quote(paper.arxiv_id, safe=''),
              'matched_fields': [], 'conflicts': [], 'registry_metadata': {}}
    try:
        matches = parse_feed(client.request(API, {'id_list': paper.arxiv_id}))
        if len(matches) != 1:
            raise ValueError('arXiv did not return exactly one record')
        found = matches[0]
        record['registry_metadata'] = {'arxiv_id': found.arxiv_id, 'title': found.title,
                                       'published': found.published, 'status': 'preprint'}
        checks = {'arxiv_id': found.arxiv_id == paper.arxiv_id,
                  'title': normalize_text(found.title) == normalize_text(paper.title)}
        if paper.published and paper.venue_canonical == 'arXiv':
            checks['publication_date'] = paper.published[:10] == found.published
        for field, matched in checks.items():
            record['matched_fields' if matched else 'conflicts'].append(field)
        record['status'] = 'registry_agreement' if not record['conflicts'] else 'conflicting_metadata'
        record['reason'] = 'Direct arXiv record lookup; journal references are not acceptance evidence'
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        record['reason'] = f'arXiv check unavailable: {exc}'
    return record
