"""Unit and end-to-end tests run fully offline: python -m unittest discover -s tests -v."""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from literature_scout.models import Paper, normalize_doi, normalize_arxiv
from literature_scout.dedup import deduplicate
from literature_scout.venues import gate, match_venue
from literature_scout.ranking import plan_queries, score_papers
from literature_scout.sources import openalex, semantic_scholar, arxiv, dblp
from literature_scout.monitor import update_state
from literature_scout.pipeline import run_scan
from literature_scout.config import load_config, DEFAULT
from literature_scout.reporting import make_report, export_result
from literature_scout.cli import main

ROOT = Path(__file__).resolve().parents[1]

class NormalizationTests(unittest.TestCase):
    def test_doi(self):
        self.assertEqual(normalize_doi('https://doi.org/10.1234/ABC'), '10.1234/abc')
        self.assertEqual(normalize_doi('doi: 10.1000/XYZ.'), '10.1000/xyz')

    def test_arxiv_version(self):
        self.assertEqual(normalize_arxiv('https://arxiv.org/abs/2401.00001v3'), '2401.00001')

    def test_venue_alias(self):
        self.assertEqual(match_venue('Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition', ['CVPR']), 'CVPR')
        self.assertEqual(match_venue('International Conference on Learning Representations', ['ICLR']), 'ICLR')
        self.assertEqual(match_venue('IEEE Transactions on Medical Imaging', ['IEEE TMI']), 'IEEE TMI')

    def test_no_workshop_leak(self):
        self.assertEqual(match_venue('CVPR Workshops', ['CVPR']), '')
        self.assertIsNone(gate(Paper(title='x', venue_raw='CVPR Workshops'),venues=['CVPR'],include_arxiv=False))

    def test_preprint_not_venue(self):
        p = Paper(title='Paper submitted to CVPR 2026', abstract='Accepted at CVPR?',
                  venue_raw='arXiv', arxiv_id='2601.11111')
        self.assertIsNone(gate(p, venues=['CVPR'], include_arxiv=False))
        self.assertEqual(gate(p, venues=['CVPR'], include_arxiv=True).venue_canonical, 'arXiv')

    def test_custom_venue_alias(self):
        self.assertEqual(match_venue('Journal of Extremely Useful Methods', ['JEUM'],
                {'JEUM': ['Journal of Extremely Useful Methods']}), 'JEUM')

    def test_merge_doi_title_and_sources(self):
        papers = [Paper(title='Same Study', year=2026, venue_raw='arXiv',
                        doi='10.9999/a', arxiv_id='2501.11111', sources=['arxiv'], abstract='Original'),
                  Paper(title='Same Study', year=2026, venue_raw='ICLR',
                        doi='https://doi.org/10.9999/A', sources=['semantic_scholar'], abstract='Bigger abstract')]
        result = deduplicate(papers)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].venue_raw, 'ICLR')
        self.assertEqual(set(result[0].sources), {'arxiv','semantic_scholar'})
        self.assertEqual(result[0].arxiv_id, '2501.11111')

    def test_do_not_merge_different_years(self):
        a = Paper(title='Generic Survey Title', year=2020)
        b = Paper(title='Generic Survey Title', year=2025)
        self.assertEqual(len(deduplicate([a,b])), 2)

    def test_plan_and_rank(self):
        queries = plan_queries('We investigate complementary spiking attention for medical segmentation.', max_queries=3)
        self.assertGreaterEqual(len(queries), 1)
        candidates = score_papers([Paper(title='Other topic',year=2026),
                                   Paper(title='Complementary spiking attention for medical segmentation',year=2026)],
                                  'complementary spiking attention for medical segmentation', current_year=2026)
        self.assertTrue(candidates[0].title.startswith('Complementary'))

class AdapterTests(unittest.TestCase):
    def test_openalex_inverted_abstract(self):
        p = openalex.parse_record({'display_name':'Study','publication_year':2025,
                'abstract_inverted_index':{'Spiking':[0],'attention':[1],'works':[2]},
                'primary_location':{'source':{'display_name':'ICLR'}}, 'authorships':[]})
        self.assertEqual(p.abstract, 'Spiking attention works')
        self.assertEqual(p.venue_raw, 'ICLR')

    def test_semantic_scholar(self):
        p = semantic_scholar.parse_record({'paperId':'abc','title':'Paper','year':2025,
            'externalIds':{'DOI':'10.1000/ABC','ArXiv':'2510.12345'},
            'venue':'MICCAI', 'authors':[{'name':'Jane'}], 'openAccessPdf':{'url':'https://example.org/a.pdf'}})
        self.assertEqual(p.doi, '10.1000/abc')
        self.assertEqual(p.arxiv_id, '2510.12345')
        self.assertEqual(p.authors, ['Jane'])

    def test_dblp_single_hit(self):
        found = dblp.parse_response({'result':{'hits':{'hit':{'info':{
            'title':'A Paper','year':'2025','booktitle':'MICCAI','authors':{'author':'Someone'}
        }}}}})
        self.assertEqual(found[0].venue_raw, 'MICCAI')
        self.assertEqual(found[0].authors, ['Someone'])

    def test_arxiv_atom(self):
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <id>http://arxiv.org/abs/2505.12345v2</id><title> Test Novelty </title>
          <published>2025-05-06T00:00:00Z</published><summary>A test summary.</summary>
          <author><name>Researcher</name></author></entry></feed>'''
        found = arxiv.parse_feed(xml)
        self.assertEqual(found[0].arxiv_id, '2505.12345')
        self.assertEqual(found[0].venue_raw, 'arXiv')
        self.assertEqual(found[0].year, 2025)

class PipelineTests(unittest.TestCase):
    def test_fixture_pipeline_and_reports(self):
        cfg = load_config(ROOT/'config'/'medqkformer.json')
        cfg['since'] = 2024  # Test fixture coverage independently of the live topic cutoff.
        result = run_scan(cfg, 'complementary spike attention medical segmentation',
                offline_fixture=str(ROOT/'examples'/'synthetic_fixture.json'))
        self.assertTrue(result.fixture_mode)
        self.assertEqual(len(result.papers), 2)
        self.assertTrue(all(p.venue_canonical in {'ICLR','arXiv'} for p in result.papers))
        self.assertIn('SYNTHETIC FIXTURES', make_report(result))
        with tempfile.TemporaryDirectory() as td:
            export_result(result, Path(td))
            self.assertTrue((Path(td)/'papers.bib').exists())
            self.assertEqual(len(json.loads((Path(td)/'papers.json').read_text())), 2)

    def test_watch_first_run_then_diff(self):
        a = Paper(title='Example A', year=2026, doi='10.1000/a')
        b = Paper(title='Example B', year=2026, doi='10.1000/b')
        with tempfile.TemporaryDirectory() as td:
            state = Path(td)/'state.json'
            self.assertEqual(update_state([a],state_file=state), [])
            self.assertEqual([p.title for p in update_state([a,b],state_file=state)], ['Example B'])
            self.assertEqual(update_state([a,b],state_file=state), [])

    def test_cli_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            exit_code = main(['scan', '--config', str(ROOT/'config'/'medqkformer.json'),
                              '--offline-fixture', str(ROOT/'examples'/'synthetic_fixture.json'),
                              '--out', td])
            self.assertEqual(exit_code, 0)
            self.assertTrue((Path(td)/'report.md').exists())

if __name__ == '__main__':
    unittest.main()
