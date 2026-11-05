"""Scientific workflow tests with synthetic evidence and mocked providers/LLM."""
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from literature_scout.config import DEFAULT, load_config
from literature_scout.models import Paper
from literature_scout.pipeline import ScanResult
from literature_scout.research_profile import ResearchProfile
from literature_scout.query_planner import plan_research_queries
from literature_scout.paper_retriever import retrieve_research
from literature_scout.research_evidence import (PAPER_FIELDS, IDEA_FIELDS, CRITERIA, evidence_inventory,
                                              validate_claims)
from literature_scout.paper_analyzer import analyze_papers
from literature_scout.idea_generator import generate_ideas
from literature_scout.research_ranker import rank_directions
from literature_scout.research import run_research, load_local_texts
from literature_scout.venue_verifier import verify_paper

ROOT = Path(__file__).resolve().parents[1]


def claim(pid, *, kind='inferred'):
    return {'text': 'Synthetic interpretation for testing only', 'kind': kind,
            'evidence': [{'paper_id': pid, 'quote': 'Synthetic evidence'}] if kind != 'unknown' else []}


def completion(instructions, data, schema, **kwargs):
    pid = next(iter(data['inventory']))
    if 'papers' in schema['properties']:
        return {'papers': [{'paper_id': key, **{f: claim(key, kind='supported') for f in PAPER_FIELDS}}
                           for key in data['inventory']]}
    idea = {'id': 'I1', 'title': 'Synthetic proposal', 'closest_papers': [pid],
            **{f: claim(pid, kind='proposal') for f in IDEA_FIELDS},
            'evaluation': {k: {'score': 3, 'rationale': claim(pid)} for k in CRITERIA}}
    return {'gaps': [claim(pid)], 'ideas': [idea],
            'agenda': [{'stage': 'Pilot', 'action': claim(pid, kind='proposal'),
                        'exit_criterion': 'Refute if held-out calibration fails to improve', 'idea_ids': ['I1']}]}


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.profile = ResearchProfile('Synthetic test', 'anomaly survival',
            bridges=['survival analysis', 'continual anomaly detection'],
            foundations=['sequential testing'], contact='private@example.org')
        self.paper = Paper(title='Synthetic paper', year=2026, published='2026-11-01',
                           abstract='Synthetic evidence for tests only.', doi='10.0000/synthetic')
        self.inventory = evidence_inventory([self.paper])
        self.pid = next(iter(self.inventory))

    def test_profiles_and_configs_load(self):
        for slug in ('survival_continual', 'gan_continual', 'peft_agentic'):
            profile = ResearchProfile.load(ROOT/f'config/profiles/{slug}.json')
            self.assertNotIn('contact', profile.scientific_context())
            self.assertTrue(load_config(ROOT/f'config/{slug}.json')['queries'])
            plan = plan_research_queries(profile)
            self.assertTrue(plan['foundational'])
            self.assertLessEqual(len(plan['recent']), profile.max_queries)

    def test_quote_and_id_validation(self):
        validate_claims(claim(self.pid), self.inventory)
        bad = claim(self.pid)
        bad['evidence'][0]['quote'] = 'Fabricated theorem'
        with self.assertRaises(ValueError):
            validate_claims(bad, self.inventory)
        with self.assertRaises(ValueError):
            validate_claims(claim('P_nonexistent'), self.inventory)
        bad = claim(self.pid)
        bad['evidence'] = []
        with self.assertRaises(ValueError):
            validate_claims(bad, self.inventory)

    def test_missing_equations_remain_unknown(self):
        data = completion('', {'inventory': self.inventory}, {'properties': {'papers': {}}})
        data['papers'][0]['mathematical_formulation'] = claim(self.pid, kind='unknown')
        result = analyze_papers(self.inventory, self.profile, model='fake', complete=lambda *a, **k: data)
        from literature_scout.theory_analyzer import theory_audit
        self.assertTrue(theory_audit(result)[0]['requires_full_text_review'])

    def test_fabricated_paper_analysis_rejected(self):
        data = completion('', {'inventory': self.inventory}, {'properties': {'papers': {}}})
        data['papers'][0]['paper_id'] = 'P_FAKE'
        with self.assertRaises(ValueError):
            analyze_papers(self.inventory, self.profile, model='fake', complete=lambda *a, **k: data)

    def test_unverified_proposal_cannot_be_established_finding(self):
        data = completion('', {'inventory': self.inventory}, {'properties': {}})
        data['ideas'][0]['hypothesis']['kind'] = 'supported'
        with self.assertRaises(ValueError):
            generate_ideas(self.inventory, {}, self.profile, model='fake', complete=lambda *a, **k: data)

    def test_ratings_bounded_and_ranking_transparent(self):
        result = generate_ideas(self.inventory, {}, self.profile, model='fake', complete=completion)
        self.assertEqual(rank_directions(result['ideas'])[0]['mean_score'], 3)
        result['ideas'][0]['evaluation']['novelty']['score'] = 6
        with self.assertRaises(ValueError):
            generate_ideas(self.inventory, {}, self.profile, model='fake', complete=lambda *a, **k: result)

    def test_recent_and_foundational_branches(self):
        old = Paper(title='Old foundation', year=1990, published='1990-01-01', abstract='Synthetic evidence')
        unknown_date = Paper(title='Unknown date', year=2026)
        recent_result = ScanResult(DEFAULT, '', [], [self.paper, old, unknown_date])
        foundation_result = ScanResult(DEFAULT, '', [], [old])
        scan = Mock(side_effect=[recent_result, foundation_result])
        papers, provenance = retrieve_research(DEFAULT, self.profile, today=date(2026, 11, 5), scanner=scan)
        self.assertEqual({p.title for p in papers}, {'Synthetic paper', 'Old foundation'})
        self.assertEqual(scan.call_args_list[1].args[0]['since'], 1900)
        self.assertIn('foundational', provenance['roles'].values())

    def test_crossref_conflicts_and_outage(self):
        client = Mock()
        client.json.return_value = {'message': {'DOI': self.paper.doi, 'title': ['Different paper'],
                                                'published': {'date-parts': [[2025]]}}}
        result = verify_paper(self.paper, client=client)
        self.assertEqual(result['status'], 'conflicting_metadata')
        self.assertIn('title', result['conflicts'])
        client.json.side_effect = RuntimeError('offline')
        self.assertEqual(verify_paper(self.paper, client=client)['status'], 'unverified')
        verify_paper(self.paper, client=client, enabled=False)
        self.assertEqual(client.json.call_count, 2)

    def test_full_workflow_privacy_handoff_and_success_state(self):
        retriever = Mock(return_value=([self.paper], {'fixture_mode': True, 'branches': {}}))
        sent_to_llm = []
        def complete(instructions, data, schema, **kw):
            sent_to_llm.append(json.dumps(data))
            return completion(instructions, data, schema, **kw)
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            state = folder/'seen.json'
            run_research(DEFAULT, self.profile, folder, offline_fixture='synthetic', state_file=state,
                         complete=complete, retriever=retriever)
            self.assertNotIn(self.profile.contact, ''.join(sent_to_llm))
            bundle = json.loads((folder/'research.json').read_text())
            self.assertEqual(bundle['retrieval']['new_paper_ids'], [self.pid])
            handoff = json.loads((folder/'agentic_handoff.json').read_text())
            self.assertFalse(handoff['execution_authorized'])
            self.assertIn('SYNTHETIC', (folder/'research.txt').read_text())
            run_research(DEFAULT, self.profile, folder, offline_fixture='synthetic', state_file=state,
                         complete=complete, retriever=retriever)
            self.assertEqual(json.loads((folder/'research.json').read_text())['retrieval']['new_paper_ids'], [])

    def test_failed_analysis_does_not_advance_history(self):
        retriever = Mock(return_value=([self.paper], {'fixture_mode': True}))
        with tempfile.TemporaryDirectory() as td:
            state = Path(td)/'seen.json'
            with self.assertRaises(ValueError):
                run_research(DEFAULT, self.profile, td, offline_fixture='synthetic', state_file=state,
                             complete=lambda *a, **k: {}, retriever=retriever)
            self.assertFalse(state.exists())
            self.assertFalse((Path(td)/'agentic_handoff.json').exists())

    def test_local_full_text_hash_and_evidence_level(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            (folder/'paper.txt').write_text('Synthetic evidence with local equations')
            manifest = folder/'texts.json'
            manifest.write_text(json.dumps({self.paper.key: 'paper.txt'}))
            inventory = evidence_inventory([self.paper], load_local_texts(manifest))
            self.assertEqual(inventory[self.pid]['evidence_level'], 'user_supplied_full_text')
            self.assertNotEqual(inventory[self.pid]['sha256'], self.inventory[self.pid]['sha256'])

    def test_profile_validation(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'profile.json'
            path.write_text(json.dumps({'name': 'test', 'topic': 'test', 'max_ideas': 0}))
            with self.assertRaises(ValueError):
                ResearchProfile.load(path)


class RegistryAndTransportTests(unittest.TestCase):
    def test_arxiv_lookup_records_preprint_status(self):
        paper = Paper(title='Synthetic test', arxiv_id='2601.12345', venue_canonical='arXiv',
                      published='2026-01-02')
        client = Mock()
        client.request.return_value = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
            <id>http://arxiv.org/abs/2601.12345v2</id><title>Synthetic test</title>
            <published>2026-01-02T00:00:00Z</published></entry></feed>'''
        result = verify_paper(paper, client=client)
        self.assertEqual(result['status'], 'registry_agreement')
        self.assertIn('preprint', result['acceptance'])
        self.assertEqual(client.request.call_args.args[1], {'id_list': '2601.12345'})

    def test_structured_transport_rejects_incomplete_and_does_not_store(self):
        from unittest.mock import patch
        from literature_scout.llm import structured_research
        client = Mock()
        client.json.return_value = {'status': 'incomplete'}
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'fake'}):
            with self.assertRaises(RuntimeError):
                structured_research('instructions', {}, {}, model='fake', client=client)
        self.assertFalse(client.json.call_args.kwargs['payload']['store'])

    def test_cli_research_route(self):
        from unittest.mock import patch
        from literature_scout.cli import main
        with tempfile.TemporaryDirectory() as td:
            with patch('literature_scout.research.run_research', return_value=['research.txt']) as run:
                result = main(['research', '--config', str(ROOT/'config/survival_continual.json'),
                    '--profile', str(ROOT/'config/profiles/survival_continual.json'), '--out', td,
                    '--no-verify'])
                self.assertEqual(result, 0)
                self.assertFalse(run.call_args.kwargs['verify'])
