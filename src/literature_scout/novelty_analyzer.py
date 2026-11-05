"""Reject unsupported novelty conclusions and disconnected related-work references."""
from .research_evidence import IDEA_FIELDS


def validate_directions(data, inventory, max_ideas):
    if any(gap['kind'] not in ('inferred', 'unknown') for gap in data['gaps']):
        raise ValueError('Research gaps are corpus-limited inferences, not established absence claims')
    if not data['ideas'] or len(data['ideas']) > max_ideas:
        raise ValueError('Expected one or more research ideas within profile budget')
    ids = [idea['id'] for idea in data['ideas']]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate idea ids')
    for idea in data['ideas']:
        closest = idea['closest_papers']
        if not closest or len(closest) != len(set(closest)) or not set(closest) <= set(inventory):
            raise ValueError('Closest related publications must reference the inventory')
        for field in IDEA_FIELDS:
            if idea[field]['kind'] not in ('proposal', 'inferred', 'unknown'):
                raise ValueError('An untested research direction cannot be labeled an established finding')
        if idea['hypothesis']['kind'] != 'proposal' or idea['experiments']['kind'] != 'proposal':
            raise ValueError('Hypothesis and experimental plan must be unverified proposals')
        for rating in idea['evaluation'].values():
            if rating['rationale']['kind'] not in ('inferred', 'unknown'):
                raise ValueError('Idea ratings are judgments, not established findings')
    if not data['agenda']:
        raise ValueError('A staged agenda is required')
    for stage in data['agenda']:
        if not stage['idea_ids'] or not set(stage['idea_ids']) <= set(ids):
            raise ValueError('Agenda must refer to generated ideas')
        if stage['action']['kind'] != 'proposal':
            raise ValueError('Agenda actions must be proposals')
