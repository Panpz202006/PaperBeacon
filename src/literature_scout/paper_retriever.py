"""Reuse the established source adapters with separate recent/foundational budgets."""
from datetime import date, timedelta
from .dedup import deduplicate
from .pipeline import run_scan
from .query_planner import plan_research_queries
from .daily import in_window


def retrieve_research(config, profile, *, today=None, offline_fixture=None, scanner=run_scan):
    today = today or date.today()
    start = today - timedelta(days=profile.recent_days - 1)
    plan = plan_research_queries(profile)
    results = []
    recent_keys = set()
    for role, queries in plan.items():
        if not queries:
            continue
        cfg = {**config, 'queries': queries, 'max_queries': len(queries),
               'since': start.year if role == 'recent' else profile.foundation_since,
               'max_papers': profile.max_analysis_papers}
        if role == 'recent':
            cfg.update(_date_start=start.isoformat(), _date_end=today.isoformat())
        result = scanner(cfg, profile.topic, offline_fixture=offline_fixture)
        if role == 'recent':
            result.papers = [p for p in result.papers if in_window(p, start, today)]
            recent_keys.update(p.key for p in result.papers)
        else:
            result.papers = [p for p in result.papers if not p.year or p.year <= today.year]
        results.append((role, result))
    # Reserve evidence budget for both branches, then deduplicate across branches.
    recent = next((r.papers for role, r in results if role == 'recent'), [])
    foundations = next((r.papers for role, r in results if role == 'foundational'), [])
    budget = profile.max_analysis_papers
    reserved = min(len(foundations), max(1, budget // 3)) if budget > 1 else 0
    selected = deduplicate(recent[:budget-reserved] + foundations[:reserved])
    selected_keys = {p.key for p in selected}
    selected += [p for p in deduplicate(recent + foundations) if p.key not in selected_keys][:budget-len(selected)]
    return selected, {'plan': plan, 'window': [start.isoformat(), today.isoformat()],
                      'branches': {role: {'queries': r.queries, 'counts': r.counts, 'warnings': r.warnings}
                                   for role, r in results},
                      'roles': {p.key: ('recent' if p.key in recent_keys else 'foundational') for p in selected},
                      'fixture_mode': bool(offline_fixture)}
