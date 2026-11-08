"""Exploration relevance should reflect topic evidence rather than generic words or dates."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from literature_scout.models import Paper
from literature_scout.matching import rank_exploration, resolve_topic_weights
from literature_scout.interface import main
from literature_scout.exploration import explore

QUERY = 'survival analysis, continual learning, and anomaly detection'


class MatchingTests(unittest.TestCase):
    def test_weights_prioritize_requested_topic_over_recency(self):
        query = 'survival analysis, anomaly detection'
        survival = Paper(title='Survival analysis', year=2023)
        anomaly = Paper(title='Anomaly detection', year=2026)
        ranked, _, _ = rank_exploration([anomaly, survival], query, weights=['survival analysis=3'])
        self.assertEqual(ranked[0], survival)

    def test_relative_weight_scaling_does_not_change_scores(self):
        papers = [Paper(title='Survival analysis'), Paper(title='Anomaly detection')]
        query = 'survival analysis, anomaly detection'
        first, _, _ = rank_exploration(papers, query, weights={'survival analysis': 3, 'anomaly detection': 1})
        scores = [(p.key, p.score) for p in first]
        second, _, _ = rank_exploration(papers, query, weights={'survival analysis': 30, 'anomaly detection': 10})
        self.assertEqual(scores, [(p.key, p.score) for p in second])

    def test_default_weights_are_equal_and_aliases_are_resolved(self):
        weights = resolve_topic_weights(QUERY, ['survival=3', 'anomaly detection=2'])
        self.assertEqual(weights, {'survival analysis': 3, 'continual learning': 1, 'anomaly detection': 2})
        self.assertEqual(resolve_topic_weights('low-rank', ['low-rank=4']), {'low rank': 4})

    def test_weights_do_not_relax_all_topic_filter(self):
        paper = Paper(title='Survival analysis')
        _, evidence, _ = rank_exploration([paper], QUERY, match='all', weights=['survival=100'])
        self.assertFalse(evidence)

    def test_invalid_or_ambiguous_weights_fail_before_retrieval(self):
        for weights in (['survival=0'], ['survival=-1'], ['survival=nan'], ['survival=inf'],
                        ['unknown=2'], ['survival=2', 'survival analysis=3'], ['survival']):
            with self.subTest(weights=weights):
                client = Mock()
                with self.assertRaises(ValueError):
                    explore(QUERY, 'unused', since=2023, until=2026, client=client, weights=weights)
                client.json.assert_not_called()
                client.request.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            resolve_topic_weights('parameter efficient learning, low-rank', ['LoRA=2'])

    def test_weighted_cli_records_weights_and_ranking_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            fixture = folder/'fixture.json'
            fixture.write_text(json.dumps({'papers': [
                Paper(title='Survival analysis', year=2023, venue_raw='ICML').to_dict(),
                Paper(title='Anomaly detection', year=2026, venue_raw='ICML').to_dict()]}))
            self.assertEqual(main(['search', '--topic', 'survival analysis, anomaly detection',
                                   '--venues', 'ICML', '--since', '2023', '--until', '2026', '--top', '1',
                                   '--weight', 'survival analysis=3', '--weight', 'anomaly detection=1',
                                   '--offline-fixture', str(fixture), '--out', tmp]), 0)
            result = json.loads((folder/'papers.json').read_text())
            self.assertEqual(result[0]['title'], 'Survival analysis')
            evidence = json.loads((folder/'matching.json').read_text())
            self.assertEqual(evidence['weights']['survival analysis'], 3)
            self.assertEqual(evidence['papers'][0]['weighted_topic_coverage'], 1.5)

    def test_five_topic_query_matches_peft_and_low_rank_without_generic_efficiency(self):
        query = 'survival analysis, continual learning, parameter efficient learning, low-rank and anomaly detection'
        relevant = Paper(title='LoRA for continual survival analysis and outlier detection')
        generic = Paper(title='Efficient Learning with Low Memory and Rank Statistics')
        _, evidence, topics = rank_exploration([relevant, generic], query, match='all')
        self.assertEqual(topics, ['survival analysis', 'continual learning',
                                  'parameter efficient learning', 'low rank', 'anomaly detection'])
        self.assertEqual(len(evidence[relevant.key]['matched_topics']), 5)
        self.assertFalse(generic.matched_terms)

    def test_parameter_efficient_methods_do_not_automatically_imply_low_rank(self):
        query = 'parameter efficient learning, low-rank'
        adapter = Paper(title='PEFT via adapter tuning')
        low_rank = Paper(title='Low-rank matrix estimation')
        _, evidence, _ = rank_exploration([adapter, low_rank], query)
        self.assertEqual(evidence[adapter.key]['matched_topics'], ['parameter efficient learning'])
        self.assertEqual(evidence[low_rank.key]['matched_topics'], ['low rank'])

    def test_generic_words_alone_do_not_qualify(self):
        generic = Paper(title='Analysis of Detection and Learning Algorithms', year=2026)
        relevant = Paper(title='Outlier detection in nonstationary data', year=2023)
        ranked, evidence, topics = rank_exploration([generic, relevant], QUERY)
        self.assertFalse(generic.matched_terms)
        self.assertEqual(ranked[0], relevant)
        self.assertEqual(evidence[relevant.key]['matched_topics'], ['anomaly detection'])
        self.assertEqual(len(topics), 3)

    def test_multiple_topics_outrank_recent_single_topic(self):
        recent = Paper(title='Anomaly detection', year=2026)
        bridge = Paper(title='Continual learning for time-to-event prediction', year=2023)
        ranked, evidence, _ = rank_exploration([recent, bridge], QUERY)
        self.assertEqual(ranked[0], bridge)
        self.assertEqual(len(evidence[bridge.key]['matched_topics']), 2)

    def test_all_topics_accepts_related_expressions_but_rejects_partial_matches(self):
        full = Paper(title='Lifelong learning for survival analysis and outlier detection')
        partial = Paper(title='Lifelong learning for anomaly detection')
        _, evidence, _ = rank_exploration([partial, full], QUERY, match='all')
        self.assertEqual(set(evidence), {full.key})
        self.assertFalse(partial.matched_terms)

    def test_hyphens_plurals_and_word_boundaries(self):
        full = Paper(title='Class-incremental time-to-event models for anomalies')
        wrong = Paper(title='Discontinual survivability monomials')
        _, evidence, _ = rank_exploration([full, wrong], QUERY, match='all')
        self.assertIn(full.key, evidence)
        self.assertNotIn(wrong.key, evidence)

    def test_title_evidence_beats_abstract_and_year_only_breaks_ties(self):
        title = Paper(title='Survival analysis', year=2020)
        abstract = Paper(title='A general estimator', abstract='Survival analysis', year=2026)
        same = Paper(title='Survival analysis', year=2025)
        ranked, _, _ = rank_exploration([abstract, title, same], 'survival analysis')
        self.assertEqual(ranked, [same, title, abstract])

    def test_rare_query_words_distinguish_arbitrary_topics(self):
        common = [Paper(title=f'Federated algorithms {i}') for i in range(10)]
        specific = Paper(title='Federated privacy')
        ranked, _, _ = rank_exploration(common + [specific], 'federated privacy')
        self.assertEqual(ranked[0], specific)

    def test_repeat_terms_cannot_outweigh_more_topics(self):
        repeated = Paper(title='Anomaly ' * 100)
        bridge = Paper(title='Survival analysis and continual learning')
        ranked, _, _ = rank_exploration([repeated, bridge], QUERY)
        self.assertEqual(ranked[0], bridge)

    def test_rerank_saved_run_never_contacts_providers_and_keeps_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'
            source.mkdir()
            (source/'manifest.json').write_text(json.dumps({
                'run_utc': '2026-11-08T02:00:00Z', 'fixture_mode': False,
                'config': {'since': 2023, 'until': 2024, 'venues': ['ICML']}}))
            (source/'coverage.json').write_text(json.dumps([
                {'venue': 'ICML', 'year': 2023, 'retrieved': 1, 'pagination_complete': True},
                {'venue': 'ICML', 'year': 2024, 'pagination_complete': False, 'error': 'source unavailable'}]))
            (source/'venue-corpus.json').write_text(json.dumps([
                Paper(title='Survival analysis with continual learning and anomaly detection',
                      year=2023, venue_raw='ICML').to_dict()]))
            client = Mock()
            result = explore(QUERY, Path(tmp)/'reranked', since=2023, until=2024,
                             from_run=source, match='all', top=100, client=client)
            client.json.assert_not_called()
            client.request.assert_not_called()
            self.assertEqual(len(result.papers), 1)
            self.assertFalse(result.fixture_mode)
            self.assertEqual(result.config['source_run_utc'], '2026-11-08T02:00:00Z')
            self.assertTrue(any('source unavailable' in warning for warning in result.warnings))
            details = json.loads((Path(tmp)/'reranked/matching.json').read_text())
            self.assertEqual(len(details['papers'][0]['matched_topics']), 3)

    def test_saved_run_cannot_silently_supply_missing_venues(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            (source/'manifest.json').write_text(json.dumps({
                'run_utc': '2026-11-08', 'config': {'since': 2023, 'until': 2024, 'venues': ['ICML']}}))
            with self.assertRaisesRegex(ValueError, 'venues were not included'):
                explore(QUERY, source/'output', since=2023, until=2024, from_run=source, venues=['ICLR'])
