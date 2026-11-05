"""Strict response shapes and quote-level provenance validation."""
import hashlib
import re


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def array(items):
    return {'type': 'array', 'items': items}


TEXT = {'type': 'string'}
REFERENCE = obj({'paper_id': TEXT, 'quote': TEXT})
CLAIM = obj({'text': TEXT, 'kind': {'type': 'string', 'enum': ['supported', 'inferred', 'proposal', 'unknown']},
             'evidence': array(REFERENCE)})
PAPER_FIELDS = ('problem', 'statistical_foundation', 'mathematical_formulation', 'assumptions',
                'neural_architecture', 'contributions', 'experimental_evidence', 'limitations')
PAPER_SCHEMA = obj({'papers': array(obj({'paper_id': TEXT, **{field: CLAIM for field in PAPER_FIELDS}}))})
CRITERIA = ('scientific_significance', 'novelty', 'statistical_foundation', 'technical_feasibility',
            'empirical_testability', 'generalizability', 'computational_practicality')
IDEA_FIELDS = ('problem', 'statistical_motivation', 'mathematical_formulation', 'assumptions',
               'neural_realization', 'hypothesis', 'expected_contribution', 'experiments',
               'novelty_risks', 'limitations', 'datasets', 'baselines', 'ablations',
               'diagnostics', 'compute_plan', 'refutation_condition')
RATING = obj({'score': {'type': 'integer', 'minimum': 1, 'maximum': 5}, 'rationale': CLAIM})
IDEA_SCHEMA = obj({'gaps': array(CLAIM), 'ideas': array(obj({
    'id': TEXT, 'title': TEXT, **{field: CLAIM for field in IDEA_FIELDS},
    'closest_papers': array(TEXT), 'evaluation': obj({key: RATING for key in CRITERIA})})),
    'agenda': array(obj({'stage': TEXT, 'action': CLAIM, 'exit_criterion': TEXT, 'idea_ids': array(TEXT)}))})


def validate_shape(value, schema, path='response'):
    kind = schema['type']
    if kind == 'object':
        if not isinstance(value, dict) or set(value) != set(schema['properties']):
            raise ValueError(f'{path}: unexpected or missing fields')
        for key, child in schema['properties'].items():
            validate_shape(value[key], child, path + '.' + key)
    elif kind == 'array':
        if not isinstance(value, list):
            raise ValueError(f'{path}: expected list')
        for child in value:
            validate_shape(child, schema['items'], path)
    elif kind == 'string':
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{path}: expected nonempty string')
        if 'enum' in schema and value not in schema['enum']:
            raise ValueError(f'{path}: invalid label')
    elif kind == 'integer':
        if type(value) is not int or not schema.get('minimum', value) <= value <= schema.get('maximum', value):
            raise ValueError(f'{path}: invalid integer')


def evidence_inventory(papers, local_texts=None):
    inventory = {}
    for paper in papers:
        pid = 'P' + hashlib.sha256(paper.key.encode()).hexdigest()[:16]
        local = (local_texts or {}).get(paper.key)
        text = local if local is not None else paper.abstract
        inventory[pid] = {'paper': paper.to_dict(), 'text': text,
                          'evidence_level': 'user_supplied_full_text' if local is not None else 'abstract',
                          'sha256': hashlib.sha256(text.encode()).hexdigest()}
    return inventory


def validate_claims(value, inventory):
    if isinstance(value, dict):
        if set(value) == {'text', 'kind', 'evidence'}:
            if value['kind'] != 'unknown' and not value['evidence']:
                raise ValueError('Every non-unknown claim needs source evidence')
            if value['kind'] == 'unknown' and value['evidence']:
                raise ValueError('Unknown claims must not pretend to have evidence')
            for ref in value['evidence']:
                source = inventory.get(ref['paper_id'])
                quote = re.sub(r'\s+', ' ', ref['quote']).strip()
                if not source or not quote or quote not in re.sub(r'\s+', ' ', source['text']):
                    raise ValueError('Claim contains an unknown paper or a quote absent from its source')
        for child in value.values():
            validate_claims(child, inventory)
    elif isinstance(value, list):
        for child in value:
            validate_claims(child, inventory)
