"""Offline regression coverage for provider rate limits."""
import io
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from literature_scout.http_client import HttpClient, RateLimitError, retry_after_seconds
from literature_scout.pipeline import run_scan
from literature_scout.config import DEFAULT


class RateLimitTests(unittest.TestCase):
    def error(self, delay):
        return HTTPError('https://api.openalex.org/works', 429, 'Too Many Requests',
                         {'Retry-After': delay}, io.BytesIO(b''))

    def test_server_delay_is_respected_and_then_recovers(self):
        sleep = Mock()
        client = HttpClient(sleep=sleep)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{}'
        with patch('urllib.request.urlopen', side_effect=[self.error('35'), response]):
            self.assertEqual(client.request('https://api.openalex.org/works'), b'{}')
        sleep.assert_any_call(35)
        self.assertEqual(client.min_interval['api.openalex.org'], 2)

    def test_long_delay_is_not_truncated_or_retried_early(self):
        sleep = Mock()
        with patch('urllib.request.urlopen', side_effect=self.error('120')) as request:
            with self.assertRaisesRegex(RateLimitError, '120.0s'):
                HttpClient(sleep=sleep).request('https://api.openalex.org/works')
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()

    def test_repeated_rate_limit_has_bounded_retries(self):
        with patch('urllib.request.urlopen', side_effect=self.error('0')) as request:
            with self.assertRaises(RateLimitError):
                HttpClient(sleep=Mock()).request('https://api.openalex.org/works')
        self.assertEqual(request.call_count, 3)

    def test_retry_after_http_date(self):
        with patch('literature_scout.http_client.time.time', return_value=0):
            self.assertEqual(retry_after_seconds('Thu, 01 Jan 1970 00:02:00 GMT'), 120)
        self.assertIsNone(retry_after_seconds('invalid'))
        self.assertIsNone(retry_after_seconds('nan'))

    def test_scan_stops_rate_limited_source_and_continues_others(self):
        config = dict(DEFAULT, sources=['openalex', 'dblp'], queries=['first', 'second'],
                      openalex_semantic=True)
        with patch('literature_scout.pipeline.openalex.search',
                   side_effect=RateLimitError('quota exceeded')) as search, \
             patch('literature_scout.pipeline.openalex.semantic_search') as semantic, \
             patch('literature_scout.pipeline.dblp.search', return_value=[]) as dblp:
            result = run_scan(config, 'research')
        self.assertEqual(search.call_count, 1)
        semantic.assert_not_called()
        self.assertEqual(dblp.call_count, 2)
        self.assertTrue(any('Skipping remaining' in w for w in result.warnings))
