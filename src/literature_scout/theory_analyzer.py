"""Separate directly stated mathematics from interpretations and missing evidence."""


def theory_audit(analysis):
    return [{'paper_id': row['paper_id'],
             'foundation_status': row['statistical_foundation']['kind'],
             'formulation_status': row['mathematical_formulation']['kind'],
             'assumptions_status': row['assumptions']['kind'],
             'requires_full_text_review': any(row[key]['kind'] != 'supported' for key in
                 ('statistical_foundation', 'mathematical_formulation', 'assumptions')),
             'mathematical_correctness': 'not independently proven'} for row in analysis['papers']]
