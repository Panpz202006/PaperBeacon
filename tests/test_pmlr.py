"""Official proceedings recovery after bibliographic API failure."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from literature_scout.exploration import explore
from literature_scout.http_client import ResponseFormatError
from literature_scout.sources.pmlr import ICMLProceedings

INDEX = '<li><a href="v202"><b>Volume 202</b></a> Proceedings of ICML 2023</li>'
VOLUME = '''<h1>International Conference on Machine Learning</h1>
<div class="paper"><p class="title">Survival &amp; Anomaly Detection</p>
<p><span class="authors">Alice Smith,&nbsp;Bob Jones</span></p>
<p><a href="https://proceedings.mlr.press/v202/example23a.html">abs</a>
<a href="https://proceedings.mlr.press/v202/example23a/example23a.pdf">PDF</a></p></div>'''


class PMLRTests(unittest.TestCase):
    def test_dblp_failure_recovers_official_proceedings(self):
        client = Mock()
        client.json.side_effect = ResponseFormatError('HTML instead of JSON')
        client.request.side_effect = [INDEX.encode(), VOLUME.encode()]
        with tempfile.TemporaryDirectory() as tmp:
            result = explore('survival anomaly detection', tmp, since=2023, until=2023,
                             client=client, venues=['ICML'])
            self.assertEqual(len(result.papers), 1)
            paper = result.papers[0]
            self.assertEqual(paper.sources, ['pmlr'])
            self.assertEqual(paper.title, 'Survival & Anomaly Detection')
            self.assertEqual(paper.authors, ['Alice Smith', 'Bob Jones'])
            coverage = json.loads((Path(tmp) / 'coverage.json').read_text())
            self.assertEqual(coverage[0]['source'], 'pmlr')
            self.assertTrue(coverage[0]['pagination_complete'])
            self.assertIn('HTML instead of JSON', coverage[0]['fallback_reason'])

    def test_workshop_index_is_not_main_conference(self):
        client = Mock()
        client.request.return_value = INDEX.replace('ICML 2023', 'ICML 2023 Workshop').encode()
        with self.assertRaises(ValueError):
            ICMLProceedings(client).enumerate_year(2023)

    def test_no_false_zero_paper_claim_after_total_failure(self):
        client = Mock()
        client.json.side_effect = ResponseFormatError('HTML instead of JSON')
        client.request.side_effect = RuntimeError('PMLR unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            explore('survival analysis', tmp, since=2023, until=2023, client=client, venues=['ICML'])
            report = (Path(tmp) / 'report.txt').read_text()
            self.assertIn('No conclusion about matching papers', report)
            self.assertNotIn('No new qualifying papers today', report)
