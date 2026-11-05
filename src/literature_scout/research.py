"""Bounded scientific workflow; no autonomous experiment or email execution."""
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
from .daily import locked, save_json
from .paper_retriever import retrieve_research
from .research_evidence import evidence_inventory
from .venue_verifier import verify_paper
from .paper_analyzer import analyze_papers
from .theory_analyzer import theory_audit
from .idea_generator import generate_ideas
from .research_ranker import rank_directions
from .report_generator import export_research
from .research_monitor import research_changes
from .llm import structured_research
from .http_client import HttpClient


def load_local_texts(manifest):
    if not manifest:
        return {}
    path = Path(manifest).resolve()
    mapping = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(mapping, dict):
        raise ValueError('Full-text manifest must map Paper.key to UTF-8 text paths')
    return {key: (path.parent / value).read_text(encoding='utf-8') for key, value in mapping.items()}


def run_research(config, profile, folder, *, offline_fixture=None, verify=True, text_manifest=None,
                 state_file=None, complete=structured_research, retriever=retrieve_research,
                 verifier=verify_paper):
    folder = Path(folder)
    model = os.getenv('SCOUT_LLM_MODEL', config['llm_model'])
    # Lock state across different output folders as well as same-folder runs.
    lock_path = Path(str(state_file) + '.lock') if state_file else folder / '.research.lock'
    with locked(lock_path):
        scope = hashlib.sha256(json.dumps([profile.scientific_context(),
            {key: config[key] for key in ('venues', 'sources', 'include_arxiv', 'venue_aliases')}],
            sort_keys=True).encode()).hexdigest()
        if state_file and Path(state_file).exists():
            prior = json.loads(Path(state_file).read_text(encoding='utf-8'))
            if prior.get('scope', scope) != scope:
                raise ValueError('Research scope changed: use a separate --state file')
        papers, retrieval = retriever(config, profile, offline_fixture=offline_fixture)
        if not papers:
            raise ValueError('No evidence retrieved; cannot generate grounded research proposals')
        inventory = evidence_inventory(papers, load_local_texts(text_manifest))
        verification_client = HttpClient()
        verification = {pid: verifier(paper, client=verification_client, enabled=verify and not offline_fixture)
                        for (pid, _), paper in zip(inventory.items(), papers)}
        for pid in inventory:
            inventory[pid]['verification'] = verification[pid]
        analysis = analyze_papers(inventory, profile, model=model, complete=complete)
        directions = generate_ideas(inventory, analysis, profile, model=model, complete=complete)
        bundle = {'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
                  'model': model, 'profile': profile.scientific_context(), 'contact': profile.contact,
                  'retrieval': retrieval, 'inventory': inventory, 'verification': verification,
                  'analysis': analysis, 'theory_audit': theory_audit(analysis), 'directions': directions,
                  'ranking': rank_directions(directions['ideas'])}
        if state_file:
            state_file = Path(state_file)
            new_ids, state = research_changes(inventory, state_file, scope)
            bundle['retrieval']['new_paper_ids'] = new_ids
        artifacts = export_research(bundle, folder)
        if state_file:
            save_json(state_file, state)
        return artifacts
