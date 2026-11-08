"""Independent conference/publisher sources when the DBLP search API is unavailable."""
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse

from ..models import Paper, normalize_text
from .pmlr import ICMLProceedings

ERRORS = (OSError, ValueError, RuntimeError, KeyError, TypeError)
CROSSREF = 'https://api.crossref.org/works'


class PaperLinks(HTMLParser):
    """Collect titles only from explicit paper-detail links, never arbitrary anchors."""
    def __init__(self, base, pattern):
        super().__init__()
        self.base, self.pattern = base, re.compile(pattern)
        self.current, self.text, self.rows = None, [], {}

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            href = urljoin(self.base, dict(attrs).get('href', ''))
            if urlparse(href).netloc == urlparse(self.base).netloc and self.pattern.fullmatch(urlparse(href).path):
                self.current, self.text = href, []

    def handle_data(self, data):
        if self.current:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.current:
            title = ' '.join(''.join(self.text).split())
            # IJCAI repeats each title link with a "Details" button.
            if title and title.casefold() not in {'details', 'abstract', 'abs', 'pdf'}:
                self.rows[self.current] = title
            self.current = None


def html_papers(client, venue, year, url, pattern):
    raw = client.request(url).decode('utf-8')
    if venue == 'NeurIPS':
        # Since 2025 the year landing page may show another track and link to the main volume.
        main = re.search(rf'href=["\'](/paper_files/paper/{year}/vol\d+-main-conference/?)["\']', raw)
        if main:
            url = urljoin(url, main.group(1))
            raw = client.request(url).decode('utf-8')
    parser = PaperLinks(url, pattern)
    parser.feed(raw)
    if not parser.rows or '</html>' not in raw.casefold():
        raise ValueError(f'{venue} {year}: proceedings listing empty, unrecognized, or truncated')
    if venue == 'NeurIPS':
        declared = re.search(r'class=["\']paper-count["\']>\s*([\d,]+) papers', raw)
        if declared and int(declared.group(1).replace(',', '')) != len(parser.rows):
            raise ValueError('NeurIPS parsed paper count differs from the declared proceedings total')
    papers = [Paper(title=title, year=year, venue_raw=venue, url=link,
                    publication_type='conference', sources=['official_proceedings'],
                    notes=['Official conference paper listing; title-only topic screening.'])
              for link, title in parser.rows.items()]
    return papers, {'venue': venue, 'year': year, 'source': 'official_proceedings', 'url': url,
                    'retrieved': len(papers), 'pagination_complete': True,
                    'screening': 'title keyword overlap; abstracts not fetched'}


def crossref_year(client, venue, year):
    """Exhaust publisher deposits for a year; venue queries alone are only fuzzy matches."""
    date_filter = f'from-pub-date:{year}-01-01,until-pub-date:{year}-12-31'
    if venue == 'AAAI':
        params = {'filter': f'issn:2374-3468,{date_filter}'}
    else:
        params = {'filter': f'prefix:10.1145,type:proceedings-article,{date_filter}',
                  'query.container-title': 'ACM International Conference on Multimedia'}
    params.update(rows=1000, cursor='*', select='DOI,title,container-title,published,author,type,abstract')
    seen, papers, total, retrieved = set(), [], None, 0
    while True:
        data = client.json(CROSSREF, params)['message']
        count = int(data['total-results'])
        if total is not None and count != total:
            raise RuntimeError('Crossref index changed during pagination; retry collection')
        total = count
        items = data['items']
        if not isinstance(items, list):
            raise ValueError('Invalid Crossref page')
        if not items and retrieved < total:
            raise RuntimeError(f'Crossref pagination stopped at {retrieved} of {total}')
        for item in items:
            doi = item['DOI']
            if doi in seen:
                raise RuntimeError('Repeated Crossref record during pagination')
            seen.add(doi)
            containers = [normalize_text(t) for t in item.get('container-title', [])]
            if venue == 'AAAI':
                valid = 'proceedings of the aaai conference on artificial intelligence' in containers
            else:
                # Exact main-proceedings title; excludes companion, adjunct, and workshop volumes.
                valid = any(re.fullmatch(r'proceedings of the \d+(?:st|nd|rd|th) acm (?:international )?conference on multimedia', t)
                            for t in containers)
            if not valid:
                continue
            title = ' '.join(item.get('title', []))
            if not title or normalize_text(title) in {'preface', 'foreword', 'front matter', 'table of contents', 'author index'}:
                continue
            dates = item.get('published', {}).get('date-parts', [[]])[0]
            if not dates or dates[0] != year:
                continue
            abstract = unescape(re.sub('<[^>]+>', ' ', item.get('abstract', '')))
            authors = [' '.join(filter(None, [a.get('given'), a.get('family')])) or a.get('name', '')
                       for a in item.get('author', [])]
            papers.append(Paper(title=unescape(title), year=year, venue_raw=venue,
                                abstract=' '.join(abstract.split()), doi=doi,
                                url=f'https://doi.org/{doi}', authors=authors,
                                publication_type='conference', sources=['crossref'],
                                notes=['Publisher-deposited proceedings metadata; acceptance not independently verified.']))
        retrieved += len(items)
        if retrieved >= total:
            break
        cursor = data.get('next-cursor')
        if not cursor:
            raise RuntimeError('Crossref omitted cursor before collection completed')
        params['cursor'] = cursor
    if not papers:
        raise RuntimeError(f'No publisher-deposited {venue} {year} proceedings records found')
    return papers, {'venue': venue, 'year': year, 'source': 'crossref', 'url': CROSSREF,
                    'indexed_total': total, 'retrieved': len(papers), 'scanned_records': retrieved,
                    'pagination_complete': True, 'evidence': 'publisher-deposited metadata; not an official acceptance list'}


class Proceedings:
    def __init__(self, client):
        self.client = client
        self.icml = ICMLProceedings(client)

    def enumerate_year(self, venue, year):
        if venue == 'ICML':
            return self.icml.enumerate_year(year)
        if venue == 'NeurIPS':
            return html_papers(self.client, venue, year,
                               f'https://proceedings.neurips.cc/paper_files/paper/{year}',
                               rf'/paper_files/paper/{year}/hash/[a-f0-9]+-Abstract(?:-Conference|-Datasets_and_Benchmarks(?:_Track)?|-Position_Paper_Track)?\.html')
        if venue == 'CVPR':
            return html_papers(self.client, venue, year,
                               f'https://openaccess.thecvf.com/CVPR{year}?day=all',
                               rf'/content/CVPR{year}/html/[^/]+_paper\.html')
        if venue == 'IJCAI':
            return html_papers(self.client, venue, year, f'https://www.ijcai.org/proceedings/{year}/',
                               rf'/proceedings/{year}/\d+')
        if venue == 'ICLR':
            # Official all-papers page contains a server-rendered list, independent of OpenReview API access.
            return html_papers(self.client, venue, year, f'https://iclr.cc/virtual/{year}/papers.html',
                               rf'/virtual/{year}/poster/\d+')
        if venue in {'AAAI', 'ACM MM'}:
            return crossref_year(self.client, venue, year)
        raise ValueError(f'Unsupported proceedings venue: {venue}')
