"""DBLP bibliographic search. Excellent for CS venue names, often no abstract."""
from ..models import Paper
from ..http_client import ResponseFormatError
import xml.etree.ElementTree as ET

name = 'dblp'
API = 'https://dblp.org/search/publ/api'


def parse_response(data: dict) -> list[Paper]:
    hits = (((data.get('result') or {}).get('hits') or {}).get('hit') or [])
    if isinstance(hits, dict):
        hits = [hits]
    papers = []
    for item in hits:
        info = item.get('info') or {}
        title = info.get('title') or ''
        if not title:
            continue
        author_data = (info.get('authors') or {}).get('author') or []
        if isinstance(author_data, (str, dict)):
            author_data = [author_data]
        authors = [x if isinstance(x, str) else x.get('text', '') for x in author_data]
        year = info.get('year') or ''
        venue = info.get('venue') or info.get('booktitle') or info.get('journal') or ''
        papers.append(Paper(title=title, year=int(year) if str(year).isdigit() else None,
                            venue_raw=venue, publication_type=info.get('type') or 'unknown',
                            doi=info.get('doi') or '', url=info.get('url') or '',
                            authors=[x for x in authors if x], sources=[name],
                            identifiers={'dblp': item.get('@id') or ''}))
    return papers


def search(query: str, *, since: int, limit: int, client) -> list[Paper]:
    params = {'q': query[:200], 'format': 'json', 'h': min(200, limit), 'c': 0}
    try:
        data = client.json(API, params)
        if not isinstance(data, dict) or not isinstance(data.get('result'), dict):
            raise ResponseFormatError('dblp.org: JSON response has no search result object')
    except ResponseFormatError:
        # One documented format fallback; never parse an HTML challenge as paper data.
        xml = client.request(API, {**params, 'format': 'xml'})
        try:
            root = ET.fromstring(xml)
            if root.tag != 'result':
                raise ValueError('not a DBLP search response')
            hits = []
            for hit in root.findall('./hits/hit'):
                info = hit.find('info')
                if info is None:
                    continue
                record = {child.tag: ''.join(child.itertext()) for child in info if child.tag != 'authors'}
                record['authors'] = {'author': [''.join(a.itertext()) for a in info.findall('./authors/author')]}
                hits.append({'@id': hit.get('id', ''), 'info': record})
            data = {'result': {'hits': {'hit': hits}}}
        except (ET.ParseError, ValueError):
            raise ResponseFormatError('dblp.org: JSON and XML unavailable; possible HTML challenge or service error') from None
    return [p for p in parse_response(data) if p.year is None or p.year >= since]
