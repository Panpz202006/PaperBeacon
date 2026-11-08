"""Official ICML proceedings tables of contents, independent of DBLP."""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin
from ..models import Paper

BASE = 'https://proceedings.mlr.press/'


class Contents(HTMLParser):
    def __init__(self):
        super().__init__()
        self.papers = []
        self.paper = None
        self.field = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div' and attrs.get('class') == 'paper':
            self.paper = {'title': '', 'authors': [], 'url': '', 'pdf_url': ''}
        if self.paper is None:
            return
        if attrs.get('class') in ('title', 'authors'):
            self.field = attrs['class']
            self.text = []
        if tag == 'a':
            url = urljoin(BASE, attrs.get('href', ''))
            if url.startswith(BASE) and url.endswith('.html'):
                self.paper['url'] = url
            if url.startswith(BASE) and url.endswith('.pdf'):
                self.paper['pdf_url'] = url

    def handle_data(self, data):
        if self.field:
            self.text.append(data)

    def handle_endtag(self, tag):
        if self.paper is None:
            return
        if (self.field == 'title' and tag == 'p') or (self.field == 'authors' and tag == 'span'):
            text = ' '.join(''.join(self.text).split())
            self.paper[self.field] = text if self.field == 'title' else [a.strip() for a in text.split(',')]
            self.field = None
        if tag == 'div':
            if not self.paper['title'] or not self.paper['url']:
                raise ValueError('PMLR paper entry missing title or proceedings link')
            self.papers.append(self.paper)
            self.paper = None


class ICMLProceedings:
    def __init__(self, client):
        self.client = client
        self.volumes = None

    def enumerate_year(self, year):
        if self.volumes is None:
            html = self.client.request(BASE).decode('utf-8')
            # Exact series labels exclude workshops held at ICML.
            self.volumes = {int(y): volume for volume, y in re.findall(
                r'<li>\s*<a href="(v\d+)">.*?</a>\s*Proceedings of ICML (\d{4})\s*</li>', html)}
            if not self.volumes:
                raise ValueError('PMLR series index has no recognized ICML volumes')
        if year not in self.volumes:
            raise RuntimeError(f'Official ICML {year} proceedings not listed in PMLR index')
        url = urljoin(BASE, self.volumes[year] + '/')
        html = self.client.request(url).decode('utf-8')
        if 'International Conference on Machine Learning' not in html:
            raise ValueError('PMLR volume is not identified as ICML proceedings')
        parser = Contents()
        parser.feed(html)
        if not parser.papers or parser.paper is not None:
            raise ValueError('PMLR table of contents empty or truncated')
        papers = [Paper(**row, year=year, venue_raw='ICML', publication_type='conference',
                        sources=['pmlr'], notes=['Listed in official ICML proceedings; topic screening uses title only.'])
                  for row in parser.papers]
        if len({p.url for p in papers}) != len(papers):
            raise ValueError('PMLR table of contents contains duplicate paper links')
        return papers, {'venue': 'ICML', 'year': year, 'source': 'pmlr', 'url': url,
                        'retrieved': len(papers), 'pagination_complete': True,
                        'screening': 'title keyword overlap; abstracts not fetched'}
