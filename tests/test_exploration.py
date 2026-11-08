"""Full index pagination and uncapped local exploration exports."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from literature_scout.exploration import enumerate_year, explore


def page(total, ids):
    return {'result': {'hits': {'@total': str(total), 'hit': [
        {'@id': str(i), 'info': {'key': f'conf/icml/{i}', 'title': f'Anomaly detection {i}',
                               'year': '2025', 'venue': 'ICML'}} for i in ids]}}}


class ExplorationTests(unittest.TestCase):
    def test_pagination_uses_offsets_until_total(self):
        client = Mock()
        client.json.side_effect = [page(3, [1, 2]), page(3, [3])]
        papers, coverage = enumerate_year(client, 'ICML', 2025)
        self.assertEqual(len(papers), 3)
        self.assertTrue(coverage['pagination_complete'])
        self.assertEqual(client.json.call_args.args[1]['f'], 2)

    def test_truncation_and_repeated_pages_are_errors(self):
        for second in (page(3, []), page(3, [1])):
            client = Mock()
            client.json.side_effect = [page(3, [1, 2]), second]
            with self.assertRaises(RuntimeError):
                enumerate_year(client, 'ICML', 2025)

    def test_all_matches_exported_and_attached_with_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            fixture = folder / 'fixture.json'
            papers = [{'title': f'Anomaly detection {i}', 'year': 2025, 'venue_raw': 'ICML'} for i in range(12)]
            papers += [{'title': 'Unrelated topic', 'year': 2025, 'venue_raw': 'ICML'},
                       {'title': 'Anomaly older', 'year': 2024, 'venue_raw': 'ICML'},
                       {'title': 'Anomaly future', 'year': 2026, 'venue_raw': 'ICML'}]
            fixture.write_text(json.dumps({'papers': papers}))
            sender = Mock()
            result = explore('anomaly detection', folder, since=2025, until=2025,
                             fixture=fixture, email_to='reader@example.org', sender=sender)
            self.assertEqual(len(result.papers), 12)
            self.assertEqual(len(json.loads((folder / 'papers.json').read_text())), 12)
            self.assertEqual(len(json.loads((folder / 'venue-corpus.json').read_text())), 13)
            message = sender.call_args.args[0]
            self.assertEqual(message['to'], 'reader@example.org')
            self.assertEqual(len(message['attachments']), 3)
            report = Path(result.config['report_file'])
            self.assertRegex(report.name, r'^report-\d{8}-\d{6}-\d{6}\.txt$')
            self.assertEqual(message['attachments'][0], str(report))
            self.assertEqual(report.read_text(), (folder / 'report.txt').read_text())
            rows = report.read_text().splitlines()
            self.assertEqual(rows[0], 'Paper name\tYear\tVenue')
            self.assertEqual(len(rows), 13)
            self.assertTrue(all(len(row.split('\t')) == 3 for row in rows))
            self.assertTrue(all(row.endswith('\t2025\tICML') for row in rows[1:]))

    def test_failed_index_marks_coverage_and_keeps_local_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = Mock()
            client.json.side_effect = RuntimeError('provider unavailable')
            result = explore('anomaly detection', tmp, since=2025, until=2025, client=client)
            self.assertTrue(any('collection incomplete' in warning for warning in result.warnings))
            self.assertFalse(json.loads((Path(tmp) / 'coverage.json').read_text())[0]['pagination_complete'])
            from literature_scout.sources.dblp import API
            self.assertEqual(sum(call.args[0] == API for call in client.json.call_args_list), 1)

    def test_invalid_range_rejected_before_retrieval(self):
        client = Mock()
        with self.assertRaises(ValueError):
            explore('anomaly detection', 'unused', since=2026, until=2025, client=client)
        client.json.assert_not_called()

    def test_top_limit_keeps_highest_relevance_and_full_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            fixture = folder / 'input.json'
            fixture.write_text(json.dumps({'papers': [
                {'title': 'Anomaly methods', 'year': 2025, 'venue_raw': 'ICML'},
                {'title': 'Survival analysis anomaly detection', 'year': 2025, 'venue_raw': 'ICML'}]}))
            result = explore('survival analysis anomaly detection', folder, since=2025, until=2025,
                             fixture=fixture, top=1)
            self.assertEqual(len(result.papers), 1)
            self.assertEqual(result.papers[0].title, 'Survival analysis anomaly detection')
            self.assertEqual(result.counts['matching_records'], 2)
            self.assertEqual(len(json.loads((folder / 'venue-corpus.json').read_text())), 2)

    def test_icml_only_queries_and_filters_icml(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = Mock()
            response = page(2, [1, 2])
            response['result']['hits']['hit'][1]['info']['venue'] = 'ICLR'
            client.json.return_value = response
            result = explore('anomaly detection', tmp, since=2025, until=2025,
                             client=client, venues=['ICML'])
            client.json.assert_called_once()
            self.assertIn('stream:conf/icml:', client.json.call_args.args[1]['q'])
            self.assertEqual(result.config['venues'], ['ICML'])
            self.assertEqual(len(result.papers), 1)
            self.assertEqual(result.papers[0].venue_canonical, 'ICML')
