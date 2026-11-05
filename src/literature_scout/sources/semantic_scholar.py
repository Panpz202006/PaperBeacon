"""Semantic Scholar Academic Graph paper search."""
import os
from ..models import Paper

name = 'semantic_scholar'
API = 'https://api.semanticscholar.org/graph/v1/paper/search'
FIELDS = 'title,abstract,year,publicationDate,venue,publicationVenue,authors,url,externalIds,openAccessPdf,citationCount,publicationTypes'


def parse_record(item: dict) -> Paper:
    ids = item.get('externalIds') or {}
    pvenue = item.get('publicationVenue') or {}
    venue = pvenue.get('name') or item.get('venue') or ''
    ptypes = item.get('publicationTypes') or []
    pdf = item.get('openAccessPdf') or {}
    return Paper(title=item.get('title') or '', year=item.get('year'),
                 published=item.get('publicationDate') or '', abstract=item.get('abstract') or '',
                 venue_raw=venue, publication_type=(','.join(ptypes) or 'unknown'),
                 doi=ids.get('DOI') or '', arxiv_id=ids.get('ArXiv') or '',
                 url=item.get('url') or '', pdf_url=pdf.get('url') or '',
                 authors=[a.get('name', '') for a in item.get('authors', []) if a.get('name')],
                 citations=item.get('citationCount'),
                 identifiers={'semantic_scholar': item.get('paperId') or ''}, sources=[name])


def search(query: str, *, since: int, limit: int, client) -> list[Paper]:
    headers = {'x-api-key': os.environ['SEMANTIC_SCHOLAR_API_KEY']} if os.getenv('SEMANTIC_SCHOLAR_API_KEY') else {}
    data = client.json(API, {'query': query[:300], 'limit': min(100, limit),
                             'year': f'{since}-', 'fields': FIELDS}, headers=headers)
    return [parse_record(item) for item in data.get('data', []) if item.get('title')]
