"""CLI entrypoint: scan, watch, validate-config."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import logging
import sys
from pathlib import Path
from .config import load_config
from .pipeline import run_scan
from .reporting import export_result
from .monitor import update_state, new_papers_md
from .llm import analyze


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog='literature-scout', description='Venue-scoped academic literature scout')
    sub = ap.add_subparsers(dest='command', required=True)
    for action in ('scan','watch'):
        cmd = sub.add_parser(action, help='One-off discovery' if action == 'scan' else 'Discover newly observed records')
        cmd.add_argument('--config', required=True, help='JSON configuration')
        cmd.add_argument('--since', type=int, help='Override earliest publication year')
        mode = cmd.add_mutually_exclusive_group()
        mode.add_argument('--topic', help='Override config topic with a phrase')
        mode.add_argument('--abstract-file', help='Use abstract from plain-text file')
        cmd.add_argument('--out', default='runs/latest', help='Output folder (default: runs/latest)')
        cmd.add_argument('--offline-fixture', help='Use synthetic fixture JSON instead of external APIs')
        cmd.add_argument('--llm', action='store_true', help='Optional OpenAI abstract-only synthesis (incurs API charges)')
        cmd.add_argument('--verbose', action='store_true')
        if action == 'watch':
            cmd.add_argument('--state', default='runs/monitor-state.json', help='Persistent seen-paper state')
            cmd.add_argument('--include-existing', action='store_true', help='Emit matches on the first watch run')
    research = sub.add_parser('research', help='Evidence-grounded scientific analysis and research agenda')
    research.add_argument('--config', required=True)
    research.add_argument('--profile', required=True)
    research.add_argument('--out', default='runs/research')
    research.add_argument('--offline-fixture', help='Synthetic retrieval input; GPT analysis still requires API access')
    research.add_argument('--no-verify', action='store_true', help='Skip independent DOI registry checks')
    research.add_argument('--text-manifest', help='JSON mapping Paper.key to local UTF-8 full-text files')
    research.add_argument('--state', help='Optional research observation history; separate from delivery state')
    daily = sub.add_parser('daily', help='Send today’s GPT-ranked digest, with restart recovery')
    daily.add_argument('--config', required=True)
    daily.add_argument('--out', default='runs/daily')
    daily.add_argument('--preview', action='store_true', help='Fetch and rank without sending or advancing state')
    check = sub.add_parser('validate-config', help='Check a configuration without contacting APIs')
    check.add_argument('--config', required=True)
    return ap


def resolve_research_text(config: dict, topic: str | None, abstract_file: str | None) -> str:
    if topic is not None:
        return topic.strip()
    path = abstract_file or config['abstract_file']
    if path:
        return Path(path).read_text(encoding='utf-8').strip()
    return (config.get('topic') or '').strip()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        if getattr(args, 'since', None) is not None:
            if not 1900 <= args.since <= 9999:
                raise ValueError('since must be a four-digit year')
            cfg['since'] = args.since
        if args.command == 'validate-config':
            print('OK:', args.config)
            print('Sources:', ', '.join(cfg['sources']))
            print('Venues:', ', '.join(cfg['venues']))
            return 0
        if args.command == 'research':
            from .research import run_research
            from .research_profile import ResearchProfile
            for path in run_research(cfg, ResearchProfile.load(args.profile), args.out,
                    offline_fixture=args.offline_fixture, verify=not args.no_verify,
                    text_manifest=args.text_manifest, state_file=args.state):
                print(path)
            return 0
        if args.command == 'daily':
            from .daily import run_daily
            text = resolve_research_text(cfg, None, None)
            if not text:
                raise ValueError('Configure topic or abstract_file')
            print(run_daily(cfg, text, Path(args.out), preview=args.preview))
            return 0
        logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
        text = resolve_research_text(cfg, args.topic, args.abstract_file)
        if not text:
            raise ValueError('Provide --topic, --abstract-file, config.topic, or config.abstract_file')
        result = run_scan(cfg, text, offline_fixture=args.offline_fixture)
        out = Path(args.out)
        artifacts = export_result(result, out)
        if args.command == 'watch' and not result.papers and result.warnings:
            print('WARNING: Empty/incomplete retrieval; watch state not advanced.', file=sys.stderr)
        elif args.command == 'watch':
            state = Path(args.state)
            first = not state.exists()
            new = update_state(result.papers, state_file=state, emit_first=args.include_existing)
            file = out / 'new_papers.md'
            file.write_text(new_papers_md(new, initialized=first and not args.include_existing), encoding='utf-8')
            print(f'Newly observed: {len(new)} | state: {state} | report: {file}')
        if args.llm:
            try:
                analysis = analyze(result)
                path = out / 'llm_analysis.md'
                path.write_text(analysis, encoding='utf-8')
                print(f'LLM: {path}')
            except Exception as exc:
                print(f'WARNING: LLM analysis unavailable: {exc}', file=sys.stderr)
        print(f'Found {len(result.papers)} matches ({result.counts.get("retrieved_records",0)} raw records).')
        print('Queries: ' + ' | '.join(result.queries))
        for w in result.warnings:
            print('WARNING:', w, file=sys.stderr)
        for artifact in artifacts.values():
            print(artifact)
        return 0 if result.papers else 2
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
