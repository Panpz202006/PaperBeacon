"""Keyword selection must work without OpenAI and reject irrelevant recent papers."""
from datetime import datetime
from functools import partial
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo
from literature_scout.ranking import keyword_rank
from literature_scout.models import Paper
from literature_scout.pipeline import ScanResult
from literature_scout.daily import run_daily
from literature_scout.digest import run_digest, send_saved_digest

ROOT = Path(__file__).resolve().parents[1]


class KeywordRankingTests(unittest.TestCase):
    def test_title_weight_and_no_recency_without_relevance(self):
        papers = [Paper(title='Other subject', abstract='survival hazard', published='2026-11-05'),
                  Paper(title='Survival hazard', published='2026-11-01'),
                  Paper(title='Unrelated new paper', published='2026-11-05')]
        ranked = keyword_rank(papers, 'survival hazard')
        self.assertEqual([p.title for p in ranked], ['Survival hazard', 'Other subject'])
        self.assertEqual(ranked[0].matched_terms, ['hazard', 'survival'])

    def test_full_dates_break_ties_and_baseline_is_not_limited_to_five(self):
        papers = [Paper(title='Anomaly study '+str(i), published=f'2026-11-{i+1:02}') for i in range(8)]
        self.assertEqual(len(keyword_rank(papers, 'anomaly', baseline=True)), 8)
        self.assertEqual(len(keyword_rank(papers, 'anomaly')), 5)
        self.assertEqual(keyword_rank(papers, 'anomaly')[0].published, '2026-11-08')

    @patch.dict('os.environ', {}, clear=True)
    @patch('literature_scout.llm.rank_papers', side_effect=AssertionError('OpenAI must not be called'))
    def test_combined_collection_and_send_without_api_key(self, gpt):
        now = datetime(2026, 11, 5, 8, tzinfo=ZoneInfo('Asia/Shanghai'))
        def scanner(cfg, text):
            papers = [Paper(title=text+' hazard GAN LoRA '+str(i), abstract=text,
                            published='2026-11-04', year=2026) for i in range(3)]
            return ScanResult(cfg, text, [], papers)
        prepare = partial(run_daily, scanner=scanner)
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            result = run_digest(ROOT/'config/daily_digest.json', folder, now=now,
                                stage='collect', prepare=prepare)
            self.assertIn('no email sent', result)
            pending = json.loads((folder/'digest-state.json').read_text())['pending']
            self.assertEqual(pending['ranking_method'], 'keyword')
            self.assertNotIn('Matched terms:', pending['body'])
            self.assertNotIn('Ranking:', pending['body'])
            self.assertLessEqual(len(json.loads((folder/'collected/2026-11-05/paperbeacon-daily-2026-11-05-papers.json').read_text())), 5)
            sender = Mock()
            send_saved_digest(folder, sender=sender, now=now)
            sender.assert_called_once()
        gpt.assert_not_called()
