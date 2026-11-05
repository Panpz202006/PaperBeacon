"""arXiv Atom API. arXiv is ALWAYS classified as a preprint source."""
import re
import xml.etree.ElementTree as ET
from ..models import Paper, normalize_arxiv

name = 'arxiv'
API = 'https://export.arxiv.org/api/query'
ATOM = '{http://www.w3.org/2005/Atom}'
AX = '{http://arxiv.org/schemas/atom}'


def parse_feed(xml: bytes) -> list[Paper]:
    root = ET.fromstring(xml)
    papers = []
    for e in root.findall(f'{ATOM}entry'):
        title = ' '.join((e.findtext(f'{ATOM}title') or '').split())
        rawid = e.findtext(f'{ATOM}id') or ''
        if not title or 'arxiv.org/api/errors' in rawid:
            continue
        arxiv_id = normalize_arxiv(rawid)
        date = (e.findtext(f'{ATOM}published') or '')[:10]
        journal_ref = e.findtext(f'{AX}journal_ref') or ''
        links = e.findall(f'{ATOM}link')
        pdf = next((x.attrib.get('href') for x in links if x.attrib.get('title') == 'pdf'), '')
        doi = e.findtext(f'{AX}doi') or ''
        paper = Paper(title=title, year=int(date[:4]) if date[:4].isdigit() else None,
                      published=date, abstract=' '.join((e.findtext(f'{ATOM}summary') or '').split()),
                      venue_raw='arXiv', publication_type='preprint',
                      doi=doi, arxiv_id=arxiv_id,
                      url=f'https://arxiv.org/abs/{arxiv_id}' if arxiv_id else rawid,
                      pdf_url=pdf or '', authors=[a.findtext(f'{ATOM}name') or '' for a in e.findall(f'{ATOM}author')],
                      sources=[name], notes=([f'Unverified journal reference: {journal_ref}'] if journal_ref else []))
        for author in e.findall(f'{ATOM}author'):
            author_name = author.findtext(f'{ATOM}name') or ''
            affiliations = [' '.join(x.itertext()).strip() for x in author.findall(f'{AX}affiliation')]
            if author_name and any(affiliations):
                paper.author_affiliations[author_name] = [x for x in affiliations if x]
        if paper.author_affiliations:
            paper.affiliation_sources.append(paper.url)
        papers.append(paper)
    return papers


def search(query: str, *, since: int, limit: int, client, date_start=None, date_end=None) -> list[Paper]:
    # A small conjunction of significant terms is more reliable than sending a full abstract.
    terms = re.findall(r'[A-Za-z][A-Za-z0-9-]*', query)
    terms = [x for x in terms if len(x) > 2][:5]
    if not terms:
        return []
    expr = ' AND '.join('all:' + x for x in terms)
    if date_start:
        start_stamp = date_start.replace('-', '') + '0000'
        end_stamp = date_end.replace('-', '') + '2359'
        expr += f' AND submittedDate:[{start_stamp} TO {end_stamp}]'
    xml = client.request(API, {'search_query': expr, 'start': 0, 'max_results': min(limit, 100),
                               'sortBy': 'submittedDate', 'sortOrder': 'descending'})
    return [p for p in parse_feed(xml) if p.year is None or p.year >= since]
