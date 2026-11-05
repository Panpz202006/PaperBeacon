"""Email structure and paper-specific affiliation provenance."""
import unittest
from literature_scout.daily import plain_report
from literature_scout.dedup import deduplicate
from literature_scout.digest import topic_sections
from literature_scout.models import Paper
from literature_scout.sources import openalex, arxiv


class EmailStructureTests(unittest.TestCase):
    def test_openalex_author_institution_mapping_and_roles(self):
        p = openalex.parse_record({'display_name': 'Synthetic study', 'id': 'https://openalex.org/W_TEST',
            'authorships': [{'author': {'display_name': 'Author One'}, 'author_position': 'first',
                'institutions': [{'display_name': 'University A'}, {'display_name': 'Institute B'}]},
                {'author': {'display_name': 'Author Two'}, 'is_corresponding': True,
                 'raw_affiliation_strings': ['Lab C']} ]})
        self.assertEqual(p.author_affiliations['Author One'], ['University A', 'Institute B'])
        self.assertEqual(p.author_affiliations['Author Two'], ['Lab C'])
        self.assertIn('corresponding', p.author_roles['Author Two'])
        self.assertEqual(p.affiliation_sources, ['https://openalex.org/W_TEST'])
        self.assertEqual(Paper.from_dict(p.to_dict()).author_affiliations, p.author_affiliations)

    def test_arxiv_optional_affiliation(self):
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom"><entry>
          <id>http://arxiv.org/abs/2601.12345</id><title>Synthetic study</title>
          <author><name>Author One</name><arxiv:affiliation>University A</arxiv:affiliation></author>
          <author><name>Author Two</name></author></entry></feed>'''
        paper = arxiv.parse_feed(xml)[0]
        self.assertEqual(paper.author_affiliations, {'Author One': ['University A']})
        self.assertIn('Author Two: Affiliation not available', plain_report('Topic', [paper]))

    def test_report_author_limit_includes_explicit_corresponding_author(self):
        paper = Paper(title='Synthetic', authors=['A', 'B', 'C', 'D', 'E'],
            author_affiliations={'A': ['University A'], 'E': ['Institute E']},
            author_roles={'E': ['corresponding']})
        report = plain_report('Topic', [paper])
        self.assertIn('A: University A', report)
        self.assertIn('E [corresponding]: Institute E', report)
        self.assertNotIn('  - D:', report)
        self.assertIn('5 authors total', report)
        self.assertIn('Abstract:', report)
        self.assertIn('Links:', report)

    def test_merging_retains_affiliations_from_other_source(self):
        papers = [Paper(title='Synthetic', doi='10.0000/test', venue_raw='ICLR', authors=['A']),
                  Paper(title='Synthetic', doi='10.0000/test', authors=['A'],
                        author_affiliations={'A': ['University A']}, affiliation_sources=['https://example.org'])]
        merged = deduplicate(papers)[0]
        self.assertEqual(merged.author_affiliations['A'], ['University A'])
        self.assertIn('https://example.org', merged.affiliation_sources)

    def test_only_populated_topics_and_no_diagnostics(self):
        paper = Paper(title='Synthetic unique title', authors=['A'])
        configs = [('a', {'name': 'Survival'}), ('b', {'name': 'GANs'}), ('c', {'name': 'Agents'})]
        item = {'papers': [paper.to_dict()], 'coverage_warnings': ['source unavailable']}
        report = topic_sections(configs, [('a', configs[0][1], item), ('b', configs[1][1], item)], [paper])
        self.assertIn('Survival', report)
        self.assertNotIn('GANs', report)
        self.assertNotIn('Agents', report)
        self.assertEqual(report.count('Synthetic unique title'), 1)
        for unwanted in ('Collection unavailable', 'SOURCE COVERAGE', 'source unavailable',
                         'Cross-topic', 'No papers selected', 'Keyword relevance', 'selected paper(s)'):
            self.assertNotIn(unwanted, report)

    def test_short_topic_titles_and_empty_digest(self):
        paper = Paper(title='Test paper', abstract='Test abstract', authors=['A'],
                      author_affiliations={'A': ['University A']})
        configs = [('gan_continual', {'name': 'Generative modeling for continual anomaly detection'})]
        item = {'papers': [paper.to_dict()], 'coverage_warnings': ['cooldown: retry in 300s']}
        report = topic_sections(configs, [('gan_continual', configs[0][1], item)], [paper])
        self.assertIn('GANs & Continual Learning', report)
        self.assertIn('A — University A', report)
        self.assertNotIn('Generative modeling for continual anomaly detection', report)
        self.assertNotIn('cooldown', report)
        self.assertEqual(topic_sections(configs, [], []), 'No new papers today.')
