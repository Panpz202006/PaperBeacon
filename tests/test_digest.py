"""Combined delivery: one email and no history loss after partial failures."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from literature_scout.daily import save_json
from literature_scout.digest import run_digest
from literature_scout.models import Paper

ROOT = Path(__file__).resolve().parents[1]


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.now = datetime(2026, 11, 5, 8, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.send = Mock()
        def prepare(cfg, topic, folder, **kwargs):
            papers = [Paper(title=f'{cfg["name"]} {i}', published='2026-11-04').to_dict() for i in range(5)]
            message = {'papers': papers}
            if not kwargs['preview']:
                save_json(folder/'daily-state.json', {'reported': [], 'deliveries': {}, 'pending': message})
            return message
        self.prepare = Mock(side_effect=prepare)
        self.rank = Mock(side_effect=lambda papers, *a, **kw: papers[:5])

    def run_job(self, **kwargs):
        return run_digest(ROOT/'config/daily_digest.json', self.folder, now=self.now,
                          sender=self.send, prepare=self.prepare, ranker=self.rank, **kwargs)

    def test_one_email_five_total_and_repeat_suppressed(self):
        self.run_job()
        self.send.assert_called_once()
        self.assertEqual(len(self.send.call_args.args[0]['tokens']), 5)
        for slug in ('survival_continual', 'gan_continual', 'peft_agentic'):
            state = json.loads((self.folder/slug/'daily-state.json').read_text())
            self.assertEqual(len(state['reported']), 5)
            self.assertNotIn('pending', state)
        self.assertEqual(self.run_job(), 'Already sent today')
        self.send.assert_called_once()

    def test_smtp_failure_keeps_exact_outbox_and_does_not_advance(self):
        self.send.side_effect = OSError('offline')
        with self.assertRaises(OSError):
            self.run_job()
        old = json.loads((self.folder/'digest-state.json').read_text())
        self.assertEqual(old['reported'], [])
        self.send.side_effect = None
        self.run_job()
        self.assertEqual(self.send.call_args.args[0]['message_id'], old['pending']['message_id'])
        self.assertEqual(self.prepare.call_count, 3)

    def test_accepted_email_bookkeeping_recovers_without_resending(self):
        from unittest.mock import patch
        with patch('literature_scout.digest.finalize', side_effect=OSError('disk interrupted')):
            with self.assertRaises(OSError):
                self.run_job()
        self.run_job()
        self.send.assert_called_once()

    def test_preview_no_email_or_state(self):
        self.run_job(preview=True)
        self.send.assert_not_called()
        self.assertFalse((self.folder/'digest-state.json').exists())
        self.assertTrue((self.folder/'preview.txt').exists())

    def test_incomplete_topic_does_not_send(self):
        self.prepare.side_effect = RuntimeError('source failed')
        with self.assertRaises(RuntimeError):
            self.run_job()
        self.send.assert_not_called()

    def test_two_stages_collection_then_offline_send(self):
        from literature_scout.digest import send_saved_digest
        result = run_digest(ROOT/'config/daily_digest.json', self.folder, now=self.now,
                            sender=self.send, prepare=self.prepare, ranker=self.rank, stage='collect')
        self.assertIn('no email sent', result)
        self.send.assert_not_called()
        archive = self.folder/'collected/2026-11-05'
        self.assertTrue((archive/'survival_continual-2026-11-05-papers.json').exists())
        self.assertTrue((archive/'anomaly-research-2026-11-05-report.txt').exists())
        email = json.loads((archive/'anomaly-research-2026-11-05-email.json').read_text())
        self.assertIn('Survival, GANs & Agentic AI', email['subject'])
        self.assertIn('2026-11-05 | 5 papers', email['subject'])
        self.prepare.reset_mock()
        self.rank.reset_mock()
        send_saved_digest(self.folder, sender=self.send, now=self.now)
        self.send.assert_called_once()
        self.prepare.assert_not_called()
        self.rank.assert_not_called()
        send_saved_digest(self.folder, sender=self.send, now=self.now)
        self.send.assert_called_once()

    def test_send_without_collection_never_sends(self):
        from literature_scout.digest import send_saved_digest
        self.assertIn('collect first', send_saved_digest(self.folder, sender=self.send))
        self.send.assert_not_called()
