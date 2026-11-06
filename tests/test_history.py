"""Historical fallback prioritization and durable delivery regression coverage."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from zoneinfo import ZoneInfo
from literature_scout.config import load_config
from literature_scout.daily import save_json
from literature_scout.digest import run_digest
from literature_scout.history import historical_shortlists
from literature_scout.models import Paper
from literature_scout.monitor import identity_tokens
from literature_scout.ranking import keyword_rank

ROOT = Path(__file__).resolve().parents[1]

class HistoricalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.now = datetime(2026, 11, 6, 8, tzinfo=ZoneInfo('Asia/Shanghai'))
        settings = json.loads((ROOT/'config/daily_digest.json').read_text())
        self.configs = [(Path(name).stem, load_config(ROOT/'config'/name)) for name in settings['topics']]
        for slug, cfg in self.configs:
            scope = {key: cfg[key] for key in ('venues', 'include_arxiv', 'sources', 'queries', 'venue_aliases')}
            fingerprint = hashlib.sha256(json.dumps([cfg['topic'], scope], sort_keys=True).encode()).hexdigest()
            save_json(self.folder/slug/'daily-state.json', {'scope': fingerprint, 'baseline': True,
                      'reported': [], 'deliveries': {}})
        self.old = Paper(title='Survival anomaly detection hazard', year=2026, published='2026-09-01', doi='10.0000/history')
        self.recent = Paper(title='Survival anomaly detection hazard recent', year=2026, published='2026-11-05', doi='10.0000/recent')
        save_json(self.folder/self.configs[0][0]/'baseline-candidates.json', [self.old.to_dict()])
        self.sender = Mock()
        self.prepare = Mock(side_effect=self.empty)
    def empty(self, cfg, text, folder, **kwargs):
        state = json.loads((folder/'daily-state.json').read_text())
        state['pending'] = {'day': '2026-11-06', 'papers': []}
        save_json(folder/'daily-state.json', state)
        return state['pending']
    def run_job(self):
        return run_digest(ROOT/'config/daily_digest.json', self.folder, now=self.now,
                          prepare=self.prepare, sender=self.sender)
    def test_historical_delivery_label_and_no_repeat(self):
        self.run_job()
        sent = self.sender.call_args.args[0]
        self.assertEqual(sent['selection_mode'], 'historical')
        self.assertIn('Historical picks', sent['body'])
        self.assertIn('2026-09-01', sent['body'])
        self.assertNotIn('No new papers', sent['body'])
        for slug, _ in self.configs:
            state = json.loads((self.folder/slug/'daily-state.json').read_text())
            self.assertNotIn('pending', state)
        history, _ = historical_shortlists(self.configs, self.folder, self.now.date(), [], keyword_rank)
        self.assertEqual(history, [])
        self.assertEqual(self.run_job(), 'Already sent today')
        self.sender.assert_called_once()
    def test_recent_papers_take_priority_without_historical_filler(self):
        self.prepare.side_effect = lambda *a, **kw: {'papers': [self.recent.to_dict()]}
        self.run_job()
        sent = self.sender.call_args.args[0]
        self.assertEqual(sent['selection_mode'], 'recent')
        self.assertIn(self.recent.title, sent['body'])
        self.assertNotIn(self.old.title+'\n', sent['body'])
        self.assertEqual(len(sent['tokens']), 2)
    def test_failure_preserves_unsent_history_and_retries_exact_outbox(self):
        self.sender.side_effect = OSError('offline')
        with self.assertRaises(OSError): self.run_job()
        state = json.loads((self.folder/'digest-state.json').read_text())
        self.assertEqual(state['reported'], [])
        pending_id = state['pending']['message_id']
        self.sender.side_effect = None
        self.run_job()
        self.assertEqual(self.sender.call_args.args[0]['message_id'], pending_id)
        self.assertEqual(self.prepare.call_count, 3)
    def test_history_is_available_even_when_live_sources_fail(self):
        self.prepare.side_effect = RuntimeError('sources offline')
        self.run_job()
        self.assertEqual(self.sender.call_args.args[0]['selection_mode'], 'historical')
        self.assertTrue(self.sender.call_args.args[0]['coverage_warnings'])
    def test_exclude_reported_future_recent_and_wrong_topic_scope(self):
        slug, _ = self.configs[0]
        future = Paper(title='Survival anomaly future', year=2027, published='2027-01-01')
        save_json(self.folder/slug/'baseline.json', [self.recent.to_dict(), future.to_dict(), self.old.to_dict()])
        selected, _ = historical_shortlists(self.configs, self.folder, self.now.date(), identity_tokens(self.old), keyword_rank)
        self.assertEqual(selected, [])
        state = json.loads((self.folder/slug/'daily-state.json').read_text());state['scope']='different'
        save_json(self.folder/slug/'daily-state.json', state)
        self.assertEqual(historical_shortlists(self.configs,self.folder,self.now.date(),[],keyword_rank)[0],[])
