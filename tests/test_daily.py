"""Offline delivery lifecycle and ranking validation tests."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from literature_scout.config import DEFAULT
from literature_scout.daily import in_window, run_daily, locked
from literature_scout.llm import rank_papers
from literature_scout.models import Paper
from literature_scout.pipeline import ScanResult


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {**DEFAULT, 'topic': 'attention'}
        self.now = datetime(2026, 11, 5, 8, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.papers = [Paper(title=f'Attention {i}', published='2026-11-04', year=2026,
                             doi=f'10.1234/{i}', abstract='Attention methods') for i in range(8)]
        self.scan = Mock(return_value=ScanResult(self.cfg, 'attention', [], self.papers))
        self.rank = Mock(side_effect=lambda papers, *args, **kw: papers if kw.get('baseline') else papers[:5])
        self.send = Mock()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def run_job(self, **kwargs):
        return run_daily(self.cfg, 'attention', self.folder, now=kwargs.pop('now', self.now),
                         scanner=self.scan, ranker=self.rank, sender=self.send, **kwargs)

    def test_first_baseline_daily_and_next_day_backlog(self):
        self.run_job()
        self.assertEqual(len(json.loads((self.folder/'baseline.json').read_text())), 8)
        self.assertEqual(len(self.send.call_args.args[0]['tokens']), 10)
        self.assertEqual(self.run_job(), 'Already sent today')
        self.assertEqual(self.send.call_count, 1)
        self.run_job(now=self.now.replace(day=6))
        self.assertEqual(len(self.send.call_args.args[0]['tokens']), 6)
        self.assertEqual(self.scan.call_count, 3)

    def test_failed_send_survives_restart_without_losing_papers(self):
        self.send.side_effect = OSError('offline')
        with self.assertRaises(OSError):
            self.run_job()
        state = json.loads((self.folder/'daily-state.json').read_text())
        self.assertEqual(state['reported'], [])
        pending = state['pending']
        self.send.side_effect = None
        self.run_job()
        self.assertEqual(self.send.call_args.args[0], pending)
        self.assertEqual(self.scan.call_count, 2)
        self.assertNotIn('pending', json.loads((self.folder/'daily-state.json').read_text()))

    def test_before_schedule_and_preview(self):
        self.run_job(now=self.now.replace(hour=7, minute=29))
        self.scan.assert_not_called()
        self.run_job(preview=True)
        self.send.assert_not_called()
        self.assertFalse((self.folder/'daily-state.json').exists())
        self.assertTrue((self.folder/'preview.txt').exists())

    def test_partial_retrieval_does_not_send(self):
        self.scan.return_value.warnings = ['provider offline']
        with self.assertRaises(RuntimeError):
            self.run_job()
        self.send.assert_not_called()
        self.assertFalse((self.folder/'daily-state.json').exists())

    def test_dates_and_no_padding(self):
        self.scan.return_value.papers = [self.papers[0], Paper(title='old', published='2025-01-01'),
                                        Paper(title='unknown', year=2026),
                                        Paper(title='future', published='2026-11-06')]
        self.run_job()
        self.assertIn('Attention 0', self.send.call_args.args[0]['body'])
        self.assertNotIn('2. ', self.send.call_args.args[0]['body'])
        self.assertFalse(in_window(Paper(title='x', published='2026-11'), self.now.date(), self.now.date()))

    def test_changed_topic_requires_new_directory(self):
        self.run_job()
        with self.assertRaises(ValueError):
            run_daily(self.cfg, 'different topic', self.folder, now=self.now)

    def test_lock_blocks_concurrent_sender(self):
        with locked(self.folder/'.daily.lock'):
            with self.assertRaises(RuntimeError):
                self.run_job()
        self.send.assert_not_called()

    def test_pending_yesterday_then_today(self):
        self.send.side_effect = OSError('offline')
        with self.assertRaises(OSError):
            self.run_job()
        self.send.side_effect = None
        self.run_job(now=self.now.replace(day=6))
        self.assertEqual(self.send.call_args.args[0]['day'], '2026-11-05')
        self.run_job(now=self.now.replace(day=6))
        self.assertEqual(self.send.call_args.args[0]['day'], '2026-11-06')

    @patch.dict('os.environ', {'OPENAI_API_KEY': 'fake'})
    def test_invalid_gpt_ids_fail_closed(self):
        client = Mock()
        client.json.return_value = {'status': 'completed', 'output': [
            {'content': [{'type': 'output_text', 'text': '{"ids":[99]}'}]}]}
        with self.assertRaises(ValueError):
            rank_papers(self.papers, 'attention', 'model', client=client)
