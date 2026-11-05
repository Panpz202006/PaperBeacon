"""One-command routing without external calls."""
import unittest
from unittest.mock import patch
from literature_scout.interface import main


class InterfaceTests(unittest.TestCase):
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
