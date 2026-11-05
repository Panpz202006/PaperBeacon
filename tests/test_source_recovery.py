"""Persistent recovery tests: no network, credentials or real provider calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from literature_scout.config import DEFAULT
from literature_scout.daily import check_retrieval, run_daily
from literature_scout.http_client import AuthenticationError, ResponseFormatError, RateLimitError, HttpClient
from literature_scout.models import Paper
from literature_scout.pipeline import ScanResult
from literature_scout.source_recovery import SourceRecovery, recover_source
from literature_scout.sources import dblp


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = {**DEFAULT, 'recovery_dir': str(self.root), 'openalex_anonymous_fallback': True}

    def test_authentication_failure_stops_queries_and_survives_restart(self):
        adapter = Mock()
        adapter.search.side_effect = AuthenticationError('credentials rejected')
        recover_source(self.cfg, 'semantic_scholar', ['a', 'b', 'c'], adapter, Mock())
        recover_source(self.cfg, 'semantic_scholar', ['a', 'b'], adapter, Mock())
        adapter.search.assert_called_once()
        with patch.dict('os.environ', {'SEMANTIC_SCHOLAR_API_KEY': 'new-test-key'}):
            recover_source(self.cfg, 'semantic_scholar', ['a'], adapter, Mock())
        self.assertEqual(adapter.search.call_count, 2)
        self.assertNotIn('new-test-key', (self.root/'semantic_scholar.json').read_text())

    def test_retry_after_survives_process_and_blocks_all_topics(self):
        recovery = SourceRecovery(self.root, 'semantic_scholar', clock=lambda: 100)
        with recovery.session():
            error = RateLimitError('rate limited')
            error.retry_after = 7200
            recovery.fail(error)
        again = SourceRecovery(self.root, 'semantic_scholar', clock=lambda: 200)
        with again.session():
            self.assertIn('cooldown', again.blocked())
            self.assertGreaterEqual(again.state['retry_at'], 7300)

    @patch.dict('os.environ', {'OPENALEX_API_KEY': 'rejected-test-key'})
    def test_openalex_uses_public_fallback_without_repeating_bad_credentials(self):
        adapter = Mock()
        adapter.search.side_effect = [AuthenticationError('rejected'), [], []]
        _, warnings, fresh, _ = recover_source(self.cfg, 'openalex', ['a', 'b'], adapter, Mock())
        self.assertEqual(fresh, 2)
        self.assertEqual(adapter.search.call_count, 3)
        self.assertTrue(adapter.search.call_args_list[1].kwargs['anonymous'])
        self.assertTrue(adapter.search.call_args_list[2].kwargs['anonymous'])
        self.assertTrue(any('anonymous' in w for w in warnings))
        adapter.search.side_effect = None
        adapter.search.return_value = []
        recover_source(self.cfg, 'openalex', ['c'], adapter, Mock())
        self.assertTrue(adapter.search.call_args.kwargs['anonymous'])

    def test_cache_avoids_repeat_calls_and_preserves_metadata(self):
        adapter = Mock()
        adapter.search.return_value = [Paper(title='Synthetic', published='2026-11-01')]
        recover_source(self.cfg, 'arxiv', ['query'], adapter, Mock())
        papers, _, fresh, cached = recover_source(self.cfg, 'arxiv', ['query'], adapter, Mock())
        adapter.search.assert_called_once()
        self.assertEqual((fresh, cached), (0, 1))
        self.assertEqual(papers[0].published, '2026-11-01')

    def test_cache_expires_and_query_windows_do_not_mix(self):
        recovery = SourceRecovery(self.root, 'arxiv', clock=lambda: 0)
        recovery.store({'end': '2026-11-05'}, [Paper(title='Synthetic')])
        self.assertIsNone(recovery.cached({'end': '2026-11-06'}))
        recovery.clock = lambda: 21601
        self.assertIsNone(recovery.cached({'end': '2026-11-05'}))

    def test_dblp_xml_fallback_and_html_rejection(self):
        client = Mock()
        client.json.side_effect = ResponseFormatError('bad json')
        client.request.return_value = b'<result><hits><hit id="1"><info><title>Synthetic</title><year>2026</year><venue>ICLR</venue><authors><author>Test</author></authors></info></hit></hits></result>'
        papers = dblp.search('test', since=2020, limit=10, client=client)
        self.assertEqual(papers[0].authors, ['Test'])
        self.assertEqual(client.request.call_args.args[1]['format'], 'xml')
        client.request.return_value = b'<html><body>blocked</body></html>'
        with self.assertRaises(ResponseFormatError):
            dblp.search('test', since=2020, limit=10, client=client)

    def test_partial_evidence_allowed_but_total_failure_not_reported_as_no_papers(self):
        config = {**self.cfg, 'retrieval_policy': 'available'}
        result = ScanResult(config, '', [], [Paper(title='Synthetic')], warnings=['source offline'])
        check_retrieval(result, config)
        result.papers = []
        with self.assertRaises(RuntimeError):
            check_retrieval(result, config)
        result.counts['successful_queries'] = 1
        check_retrieval(result, config)
        with self.assertRaises(RuntimeError):
            check_retrieval(result, {**config, 'retrieval_policy': 'strict'})

    def test_deferred_http_429_does_not_sleep_or_retry(self):
        from urllib.error import HTTPError
        import io
        error = HTTPError('https://example.org', 429, 'rate limited', {'Retry-After': '300'}, io.BytesIO(b''))
        client = HttpClient(defer_rate_limits=True, sleep=Mock())
        with patch('urllib.request.urlopen', side_effect=error) as request:
            with self.assertRaises(RateLimitError) as caught:
                client.request('https://example.org')
        self.assertEqual(caught.exception.retry_after, 300)
        request.assert_called_once()
        client.sleep.assert_not_called()
