#!/usr/bin/env python3
"""Turn reviewed literature metadata into an Agentic Scientist task context appendix.

This is a lightweight evidence staging step, not an auto-generated novelty proof.
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--papers', required=True, help='papers.json from Literature Scout')
    ap.add_argument('--out', default='research_context.md')
    ap.add_argument('--max', type=int, default=15)
    args = ap.parse_args()
    items = json.loads(Path(args.papers).read_text(encoding='utf-8'))[:args.max]
    lines = ['# Literature context for The Agentic Scientist', '',
             'These are *candidate prior works* discovered via metadata search. ',
             'Verify full texts, accepted venues and experimental details before using as claims.', '',
             '## Candidate papers', '']
    for i, p in enumerate(items, 1):
        lines += [f'### P{i}: {p["title"]}', '',
                  f'- Year: {p.get("year") or "Unknown"}',
                  f'- Indexed venue: {p.get("venue_canonical") or "Unknown"}',
                  f'- Evidence: {p.get("venue_evidence") or "Unknown"}',
                  f'- URL: {p.get("url") or "Not available"}',
                  f'- DOI: {p.get("doi") or "Not available"}',
                  f'- Abstract: {p.get("abstract") or "Unavailable"}', '']
    lines += ['## Required research-agent behavior', '',
              '- Treat publication metadata as preliminary, not acceptance proof.',
              '- Do not assert novelty or methodological equivalence from abstracts alone.',
              '- Identify which closest methods need full-text equation comparison.',
              '- Convert apparent gaps into falsifiable competing hypotheses, not claims of firstness.', '']
    Path(args.out).write_text('\n'.join(lines), encoding='utf-8')
    print('Wrote', args.out)

if __name__ == '__main__':
    main()
