"""Combined delivery: one email and no history loss after partial failures."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from literature_scout.daily import save_json
from literature_scout.digest import run_digest
from literature_scout.models import Paper

ROOT = Path(__file__).resolve().parents[1]


class DigestTests(unittest.TestCase):
    @patch.dict('os.environ', {'SCOUT_CHONG_PENG_EMAIL_TO': 'peng@example.org,guo@example.org'})
    def test_professor_digest_keeps_its_recipient_in_saved_outbox(self):
        from literature_scout.digest import send_saved_digest
        manifest = ROOT/'config/chong_peng/daily_digest.json'
        result = run_digest(manifest, self.folder, now=self.now, sender=self.send,
                            prepare=self.prepare, ranker=self.rank, stage='collect')
        self.assertIn('no email sent', result)
        self.send.assert_not_called()
        pending = json.loads((self.folder/'digest-state.json').read_text())['pending']
        self.assertEqual(pending['to'], 'peng@example.org,guo@example.org')
        self.assertEqual(pending['subject'],
                         'PaperBeacon Daily | ML, Subspace Clustering & Multi-view Learning | 2026-11-05 | 5 papers')
        self.assertNotIn('Anomaly Detection Research', pending['subject'])
        self.assertEqual(set(pending['children']), {'machine_learning', 'subspace_clustering', 'multi_view_learning'})
        send_saved_digest(self.folder, sender=self.send, now=self.now)
        self.assertEqual(self.send.call_args.args[0]['to'], 'peng@example.org,guo@example.org')
        self.assertEqual(run_digest(manifest, self.folder, now=self.now, sender=self.send,
                                   prepare=self.prepare, ranker=self.rank), 'Already sent today')
        self.send.assert_called_once()

    @patch.dict('os.environ', {'SCOUT_CHONG_PENG_EMAIL_TO': 'peng@example.org,guo@example.org'})
    def test_professor_digest_waits_until_eight_shanghai_time(self):
        now = self.now.replace(hour=7, minute=59)
        result = run_digest(ROOT/'config/chong_peng/daily_digest.json', self.folder,
                            now=now, sender=self.send, prepare=self.prepare, ranker=self.rank)
        self.assertEqual(result, 'Waiting until 08:00')
        self.prepare.assert_not_called()
        self.send.assert_not_called()

    @patch.dict('os.environ', {'SCOUT_EMAIL_TO': 'unrelated@example.org'}, clear=True)
    def test_private_recipient_missing_does_not_use_another_reports_address(self):
        with self.assertRaisesRegex(ValueError, 'Missing private recipient setting'):
            run_digest(ROOT/'config/chong_peng/daily_digest.json', self.folder, now=self.now,
                       sender=self.send, prepare=self.prepare, ranker=self.rank)
        self.send.assert_not_called()
        self.prepare.assert_not_called()

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
        self.assertTrue((archive/'survival_continual-daily-2026-11-05-papers.json').exists())
        self.assertTrue((archive/'paperbeacon-daily-2026-11-05-report.txt').exists())
        email = json.loads((archive/'paperbeacon-daily-2026-11-05-email.json').read_text())
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

    def test_retry_empty_replaces_only_empty_delivery(self):
        self.rank.side_effect = lambda *a, **kw: []
        self.run_job()
        self.assertEqual(len(self.send.call_args.args[0]['tokens']), 0)
        self.rank.side_effect = lambda papers, *a, **kw: papers[:5]
        result = run_digest(ROOT/'config/daily_digest.json', self.folder, now=self.now,
            sender=self.send, prepare=self.prepare, ranker=self.rank, stage='collect', retry_empty=True)
        self.assertIn('no email sent', result)
        self.assertEqual(self.send.call_count, 1)
        state = json.loads((self.folder/'digest-state.json').read_text())
        self.assertTrue(state['pending']['replaces_empty_report'])
        from literature_scout.digest import send_saved_digest
        send_saved_digest(self.folder, sender=self.send, now=self.now)
        state = json.loads((self.folder/'digest-state.json').read_text())
        self.assertEqual(len(state['superseded_empty_deliveries']), 1)
        self.assertEqual(len(state['reported']), 5)
        self.assertEqual(self.send.call_count, 2)
        with self.assertRaises(ValueError):
            run_digest(ROOT/'config/daily_digest.json', self.folder, now=self.now,
                sender=self.send, prepare=self.prepare, ranker=self.rank, stage='collect', retry_empty=True)

    def test_retry_empty_does_not_prepare_another_empty_report(self):
        self.rank.side_effect = lambda *a, **kw: []
        self.run_job()
        with self.assertRaisesRegex(RuntimeError, 'No unreported papers'):
            run_digest(ROOT/'config/daily_digest.json', self.folder, now=self.now,
                sender=self.send, prepare=self.prepare, ranker=self.rank, stage='collect', retry_empty=True)
        state = json.loads((self.folder/'digest-state.json').read_text())
        self.assertNotIn('pending', state)
        self.send.assert_called_once()
