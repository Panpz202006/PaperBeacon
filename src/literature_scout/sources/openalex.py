"""OpenAlex works lexical metadata search (does not require semantic-search credits)."""
import os
from ..models import Paper

name = 'openalex'
API = 'https://api.openalex.org/works'

def restore_abstract(inverted: dict | None) -> str:
    if not inverted:
        return ''
    tokens = {}
    for word, positions in inverted.items():
        for pos in positions:
            tokens[int(pos)] = word
    return ' '.join(tokens[p] for p in sorted(tokens))


def parse_record(item: dict) -> Paper:
    loc = (item.get('primary_location') or {})
    source = loc.get('source') or {}
    venue = source.get('display_name') or ''
    url = item.get('doi') or loc.get('landing_page_url') or item.get('id') or ''
    ptype = item.get('type') or 'unknown'
    if source.get('type') == 'repository' and not venue:
        venue = 'Repository'
    authors = [(a.get('author') or {}).get('display_name', '') for a in item.get('authorships', [])]
    affiliations, roles = {}, {}
    for authorship in item.get('authorships', []):
        author = (authorship.get('author') or {}).get('display_name')
        if not author:
            continue
        institutions = [x['display_name'] for x in authorship.get('institutions', []) if x.get('display_name')]
        raw = authorship.get('raw_affiliation_strings') or []
        affiliations[author] = list(dict.fromkeys(institutions or raw))
        roles[author] = ([authorship['author_position']] if authorship.get('author_position') else [])
        if authorship.get('is_corresponding'):
            roles[author].append('corresponding')
    return Paper(title=item.get('display_name') or item.get('title') or '',
                 year=item.get('publication_year'), published=item.get('publication_date') or '',
                 abstract=restore_abstract(item.get('abstract_inverted_index')),
                 venue_raw=venue, publication_type=ptype, doi=item.get('doi') or '',
                 url=url, pdf_url=loc.get('pdf_url') or '', authors=[a for a in authors if a],
                 author_affiliations=affiliations, author_roles=roles,
                 affiliation_sources=[item['id']] if any(affiliations.values()) and item.get('id') else [],
                 citations=item.get('cited_by_count'),
                 identifiers={'openalex': item.get('id') or ''}, sources=[name])


def search(query: str, *, since: int, limit: int, client, date_start=None, date_end=None, anonymous=False) -> list[Paper]:
    params = {'search': query[:300], 'per_page': min(100, limit),
              'filter': f'from_publication_date:{since}-01-01'}
    if date_start:
        params['filter'] = f'from_publication_date:{date_start},to_publication_date:{date_end}'
        params['sort'] = 'publication_date:desc'
    if os.getenv('OPENALEX_API_KEY') and not anonymous:
        params['api_key'] = os.environ['OPENALEX_API_KEY']
    data = client.json(API, params)
    return [parse_record(x) for x in data.get('results', []) if x.get('title') or x.get('display_name')]


def semantic_search(abstract: str, *, since: int, limit: int, client) -> list[Paper]:
    """Optional OpenAlex semantic endpoint; requires provider credits and may incur charges.

    The endpoint accepts up to 2,000 characters and at most 50 results. Opt in explicitly.
    """
    params = {'search.semantic': abstract[:2000], 'per_page': min(50, limit),
              'filter': f'from_publication_date:{since}-01-01'}
    if os.getenv('OPENALEX_API_KEY'):
        params['api_key'] = os.environ['OPENALEX_API_KEY']
    data = client.json(API, params)
    return [parse_record(x) for x in data.get('results', []) if x.get('title') or x.get('display_name')]
