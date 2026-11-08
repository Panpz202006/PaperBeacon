"""One-command routing without external calls."""
import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from literature_scout.interface import main


class InterfaceTests(unittest.TestCase):
    def test_comma_separated_venues_are_filtered_and_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            fixture = folder / 'fixture.json'
            fixture.write_text(json.dumps({'papers': [
                {'title': f'Anomaly detection {venue}', 'year': 2025, 'venue_raw': venue}
                for venue in ('ICML', 'NIPS', 'ICLR', 'CVPR')]}))
            self.assertEqual(main(['search', '--topic', 'anomaly detection',
                                   '--venues', 'ICML, NIPS,ICLR', 'ICML', '--since', '2025',
                                   '--until', '2025', '--out', tmp, '--offline-fixture', str(fixture)]), 0)
            manifest = json.loads((folder / 'manifest.json').read_text())
            self.assertEqual(manifest['config']['venues'], ['ICML', 'NeurIPS', 'ICLR'])
            self.assertEqual(len(json.loads((folder / 'papers.json').read_text())), 3)

    def test_area_search_filters_venues_preprints_workshops_and_year(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            venues = ['NIPS', 'ICML', 'ICLR', 'AAAI',
                      'Proceedings of the 32nd ACM International Conference on Multimedia',
                      'CVPR', 'IJCAI', 'ICCV', 'arXiv', 'ACM Multimedia Workshops']
            records = [{'title': f'Continual anomaly detection {i}', 'year': 2025, 'published': '2025-01-01',
                        'venue_raw': venue} for i, venue in enumerate(venues)]
            records.append({'title': 'Old anomaly detection', 'year': 2023, 'published': '2023-01-01', 'venue_raw': 'ICML'})
            fixture = folder / 'fixture.json'
            fixture.write_text(json.dumps({'papers': records}))
            description = folder / 'description.txt'
            description.write_text('Continual anomaly detection')
            for option in (['--topic', 'Continual anomaly detection'],
                           ['--abstract-file', str(description)]):
                self.assertEqual(main(['search', *option, '--since', '2025', '--out', str(folder),
                                       '--offline-fixture', str(fixture)]), 0)
                papers = json.loads((folder / 'papers.json').read_text())
                self.assertEqual(len(papers), 7)
                self.assertEqual({p['venue_canonical'] for p in papers},
                                 {'NeurIPS', 'ICML', 'ICLR', 'AAAI', 'ACM MM', 'CVPR', 'IJCAI'})

    @patch.dict('os.environ', {'OPENAI_API_KEY': 'fake'})
    @patch('literature_scout.interface.scout_main', side_effect=[0, 1, 0])
    def test_all_topics_are_isolated_and_continue_after_failure(self, run):
        self.assertEqual(main(['research', 'all', '--out', 'runs/test']), 1)
        self.assertEqual(run.call_count, 3)
        states = [call.args[0][call.args[0].index('--state') + 1] for call in run.call_args_list]
        self.assertEqual(len(set(states)), 3)
        self.assertTrue(all(path.startswith('runs/test/') for path in states))

    @patch.dict('os.environ', {'OPENAI_API_KEY': 'fake'})
    @patch('literature_scout.interface.scout_main', return_value=0)
    def test_single_topic_routing(self, run):
        self.assertEqual(main(['research', 'agents', '--no-verify']), 0)
        self.assertIn('config/peft_agentic.json', run.call_args.args[0])
        self.assertIn('--no-verify', run.call_args.args[0])
        run.assert_called_once()

    @patch('literature_scout.interface.scout_main', return_value=0)
    def test_preview_never_routes_to_send(self, run):
        self.assertEqual(main(['preview']), 0)
        self.assertIn('--preview', run.call_args.args[0])

    @patch.dict('os.environ', {}, clear=True)
    @patch('literature_scout.interface.scout_main')
    def test_missing_key_fails_before_retrieval(self, run):
        self.assertEqual(main(['research', 'all']), 1)
        run.assert_not_called()
