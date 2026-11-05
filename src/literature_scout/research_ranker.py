"""Transparent equal-weight prioritization, separate from scientific validity."""
from .research_evidence import CRITERIA


def rank_directions(ideas):
    rows = []
    for idea in ideas:
        scores = {key: idea['evaluation'][key]['score'] for key in CRITERIA}
        rows.append({'idea_id': idea['id'], 'scores': scores,
                     'mean_score': round(sum(scores.values()) / len(scores), 3),
                     'interpretation': 'Subjective model assessment; not a novelty or validity proof'})
    return sorted(rows, key=lambda row: (-row['mean_score'], row['idea_id']))
