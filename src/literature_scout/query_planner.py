"""Bounded bridge queries avoid requiring all research concepts in one paper."""


def plan_research_queries(profile):
    recent = list(dict.fromkeys([profile.topic] + profile.bridges +
                               [f'anomaly detection {m}' for m in profile.modalities]))[:profile.max_queries]
    foundational = list(dict.fromkeys(profile.foundations))[:profile.max_queries]
    return {'recent': recent, 'foundational': foundational}
