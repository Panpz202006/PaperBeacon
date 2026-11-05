"""Grounded hypotheses built from statistical problems before architecture choices."""
from .llm import structured_research
from .paper_analyzer import GUARDRAILS
from .research_evidence import IDEA_SCHEMA, validate_claims, validate_shape
from .novelty_analyzer import validate_directions


def generate_ideas(inventory, analysis, profile, *, model, complete=structured_research):
    instructions = GUARDRAILS + f'''
Generate up to {profile.max_ideas} scientifically differentiated research directions, evidence-grounded
gap analysis and a staged investigation agenda. A gap is an inference within this retrieved corpus,
not proof of absence from all literature. Cite closest publications using inventory ids.
Follow Statistical Motivation -> Mathematical Formulation -> Neural Realization -> Empirical Verification.
For each idea specify quantities, objectives, assumptions, statistical interpretation and limitations;
then a feasible architecture, falsifiable hypothesis (include a measurable prediction and refutation
condition), expected contributions and experiments. Explicitly name candidate datasets/modalities,
baselines, ablations, calibration/uncertainty and drift diagnostics, compute costs and failure tests.
These are proposed experiments, not reported results. Avoid superficial combinations, architecture
recency bias and post-hoc mathematical decoration. Contrast methodological overlap and novelty risks.
Label idea fields proposal or inferred (or unknown), never supported. Hypothesis and experiments must
be proposal. Rate all seven criteria from 1 to 5 with inferred, evidence-cited rationales. Ratings are
subjective prioritization. Agenda actions must be proposals and have measurable exit criteria.
A proposal's citations justify motivation; they do not show that the proposal already works.
'''
    result = complete(instructions, {'profile': profile.scientific_context(),
                      'inventory': inventory, 'paper_analysis': analysis}, IDEA_SCHEMA, model=model)
    validate_shape(result, IDEA_SCHEMA)
    validate_claims(result, inventory)
    validate_directions(result, inventory, profile.max_ideas)
    return result
