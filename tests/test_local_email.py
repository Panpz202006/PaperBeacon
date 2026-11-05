import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from literature_scout.local_email import read_papers, send_local


class LocalEmailTests(unittest.TestCase):
    def test_csv_fields_and_send_once(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'papers.csv'
            path.write_text('title,year,published,abstract,pdf_url\nLocal paper,2025,2025-01-01,"Abstract, with comma",https://example.org/paper.pdf\n')
            self.assertEqual(read_papers([path])[0].year, 2025)
            sender = Mock()
            send_local([path], Path(td)/'out', sender=sender, preview=True)
            sender.assert_not_called()
            send_local([path], Path(td)/'out', sender=sender)
            body = sender.call_args.args[0]['body']
            self.assertIn('Abstract, with comma', body)
            self.assertIn('not a fresh seven-day search', body)
            send_local([path], Path(td)/'out', sender=sender)
            sender.assert_called_once()

    def test_failed_send_keeps_pending_without_marking_reported(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'papers.json'
            path.write_text(json.dumps([{'title': 'Test'}]))
            sender = Mock(side_effect=OSError('offline'))
            folder = Path(td)/'out'
            with self.assertRaises(OSError):
                send_local([path], folder, sender=sender)
            state = json.loads((folder/'local-email-state.json').read_text())
            self.assertEqual(state['reported'], [])
            self.assertIn('pending', state)
            sender.side_effect = None
            send_local([path], folder, sender=sender)
            self.assertEqual(sender.call_count, 2)
