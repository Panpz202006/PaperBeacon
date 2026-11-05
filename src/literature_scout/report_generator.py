"""Plain text research intelligence and a human-review-gated agent handoff."""
import json
from pathlib import Path
from .daily import plain_report, save_json
from .research_evidence import PAPER_FIELDS, IDEA_FIELDS
from .models import Paper


def render_claim(claim):
    sources = ', '.join(sorted({ref['paper_id'] for ref in claim['evidence']})) or 'no evidence available'
    text = f'[{claim["kind"]}; {sources}] {claim["text"]}'
    for ref in claim['evidence']:
        text += f'\n    Source excerpt {ref["paper_id"]}: {ref["quote"]}'
    return text


def export_research(bundle, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    save_json(folder / 'research.json', bundle)
    lines = [bundle['profile']['name'], '',
             'DRAFT — HUMAN REVIEW REQUIRED. No experiments have been run.',
             'Source statements, interpretations and proposals are labeled separately.',
             'Quote matching establishes provenance, not scientific validity or logical entailment.', '']
    if bundle['retrieval']['fixture_mode']:
        lines += ['SYNTHETIC DEMONSTRATION — NOT REAL SCHOLARLY EVIDENCE.', '']
    if bundle.get('contact'):
        lines += ['Optional research contact (local report only): ' + bundle['contact'], '']
    lines += ['A. LITERATURE REVIEW', '']
    for pid, source in bundle['inventory'].items():
        lines += [pid, plain_report('', [Paper.from_dict(source['paper'])]),
                  'Evidence level: ' + source['evidence_level'],
                  'Verification: ' + json.dumps(bundle['verification'][pid], ensure_ascii=False), '']
    lines += ['B. TECHNICAL AND THEORETICAL COMPARISON',
              'Structured comparison rows; missing information is explicitly unknown.', '']
    for row in bundle['analysis']['papers']:
        lines += [row['paper_id']]
        for field in PAPER_FIELDS:
            lines += [field.replace('_', ' ').title() + ': ' + render_claim(row[field])]
        lines += ['']
    lines += ['Theory audit: ' + json.dumps(bundle['theory_audit'], ensure_ascii=False), '',
              'C. RESEARCH GAP ANALYSIS', '']
    lines += [render_claim(gap) for gap in bundle['directions']['gaps']]
    lines += ['', 'D. UNVERIFIED RESEARCH DIRECTIONS', '']
    for idea in bundle['directions']['ideas']:
        lines += [idea['id'] + ': ' + idea['title'], 'Closest publications: ' + ', '.join(idea['closest_papers'])]
        for field in IDEA_FIELDS:
            lines += [field.replace('_', ' ').title() + ': ' + render_claim(idea[field])]
        for key, rating in idea['evaluation'].items():
            lines += [f'{key}: {rating["score"]}/5 — ' + render_claim(rating['rationale'])]
        lines += ['']
    lines += ['E. RECOMMENDED RESEARCH AGENDA', '', 'Equal-weight subjective ranking:']
    lines += [f'{i}. {r["idea_id"]}: {r["mean_score"]}/5' for i, r in enumerate(bundle['ranking'], 1)]
    for stage in bundle['directions']['agenda']:
        lines += ['', stage['stage'] + ' — ' + ', '.join(stage['idea_ids']),
                  render_claim(stage['action']), 'Exit criterion: ' + stage['exit_criterion']]
    lines += ['', 'Retrieval coverage and warnings:', json.dumps(bundle['retrieval'], ensure_ascii=False, indent=2), '']
    (folder/'research.txt').write_text('\n'.join(lines), encoding='utf-8')
    handoff = {'status': 'awaiting_human_approval', 'execution_authorized': False,
               'instructions': ['Review references and full-text equations before adopting claims.',
                                'Obtain human approval before any experimental execution.',
                                'Treat all directions as untested proposals; assess compute and data access.'],
               'research_report': 'research.json', 'evidence_hashes': {
                   pid: source['sha256'] for pid, source in bundle['inventory'].items()},
               'ranked_directions': bundle['ranking'], 'ideas': bundle['directions']['ideas'],
               'agenda': bundle['directions']['agenda']}
    save_json(folder/'agentic_handoff.json', handoff)
    return [str(folder/name) for name in ('research.txt', 'research.json', 'agentic_handoff.json')]
