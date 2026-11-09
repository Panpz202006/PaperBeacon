"""Short commands for the repository workflow, with isolated topic histories."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from .cli import main as scout_main

TOPICS = {'survival': 'survival_continual', 'gan': 'gan_continual', 'agents': 'peft_agentic'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Literature Scout laptop interface',
        epilog='Run from the repository using: bash scripts/scout.sh COMMAND')
    sub = parser.add_subparsers(dest='command', required=True)
    search = sub.add_parser('search', help='Search a research area within the seven selected conferences')
    query = search.add_mutually_exclusive_group(required=True)
    query.add_argument('--topic', help='Keywords or a short research description')
    query.add_argument('--abstract-file', help='Read the research description from a UTF-8 file')
    search.add_argument('--since', type=int, default=2024, help='Earliest publication year (default: 2024)')
    search.add_argument('--until', type=int, help='Last publication year, inclusive (default: current year)')
    search.add_argument('--email-to', help='Email the full exploration report and attachments to this address')
    search.add_argument('--top', type=int, help='Keep only the top N papers by keyword relevance')
    search.add_argument('--match', choices=['any', 'all'], default='any', help='Require any topic or every topic (default: any)')
    search.add_argument('--weight', action='append', help='Relative topic weight, e.g. "survival analysis=3"; repeat for each topic (default: 1)')
    search.add_argument('--from-run', help='Rerank a saved exploration corpus locally; no retrieval or API calls')
    search.add_argument('--venues', nargs='+',
                        help='Comma- or space-separated venues: NeurIPS/NIPS, ICML, ICLR, AAAI, ACM MM, CVPR, IJCAI (default: all seven)')
    search.add_argument('--out', default='runs/area-search')
    search.add_argument('--offline-fixture', help='Use local fixture records instead of APIs')
    research = sub.add_parser('research', help='Generate research reports; no email or experiments')
    research.add_argument('topic', choices=['all', *TOPICS], nargs='?', default='all')
    research.add_argument('--out', default='runs/research', help='Parent directory for per-topic reports/history')
    research.add_argument('--no-verify', action='store_true')
    research.add_argument('--text-manifest')
    collect = sub.add_parser('collect', help='Stage 1: collect three-topic papers and save local files; no email')
    collect.add_argument('--config', default='config/daily_digest.json')
    collect.add_argument('--out', default='runs/daily-three-topics')
    collect.add_argument('--retry-empty', action='store_true', help='Prepare a replacement only if today’s sent report had zero papers')
    send = sub.add_parser('send', help='Stage 2: send the saved digest; no retrieval or GPT')
    send.add_argument('--out', default='runs/daily-three-topics')
    local = sub.add_parser('send-local', help='Email saved CSV/JSON papers without retrieval or GPT')
    local.add_argument('--papers', nargs='+', required=True)
    local.add_argument('--out', default='runs/local-email')
    local.add_argument('--title', help='Research topic label for the email subject')
    local.add_argument('--preview', action='store_true')
    digest = sub.add_parser('digest', help='One daily email across all three topics; at most five papers')
    digest.add_argument('--config', default='config/daily_digest.json')
    digest.add_argument('--out', default='runs/daily-three-topics')
    digest.add_argument('--preview', action='store_true')
    sub.add_parser('check', help='Validate all three topic configurations and profiles locally')
    sub.add_parser('test', help='Run the offline automated test suite')
    for action in ('preview', 'daily'):
        cmd = sub.add_parser(action, help='Preview the daily email' if action == 'preview' else 'Send the configured daily email if due')
        cmd.add_argument('--config', default=os.getenv('SCOUT_CONFIG', 'config/medqkformer.json'))
        cmd.add_argument('--out', default=os.getenv('SCOUT_OUTPUT', 'runs/daily-medqkformer'))
    sub.add_parser('schedule', help='Generate a macOS scheduler file; does not install or activate it')
    args = parser.parse_args(argv)
    if args.command == 'search':
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from .exploration import explore
        try:
            text = args.topic if args.topic is not None else Path(args.abstract_file).read_text(encoding='utf-8')
            result = explore(text, args.out, since=args.since,
                             until=args.until if args.until is not None else datetime.now(ZoneInfo('Asia/Shanghai')).year,
                             fixture=args.offline_fixture, email_to=args.email_to, venues=args.venues, top=args.top,
                             match=args.match, from_run=args.from_run, weights=args.weight)
            print(f'Saved {len(result.papers)} matching papers: {result.config["report_file"]}')
            for venue, summary in result.counts['venue_coverage'].items():
                print(f'{venue}: {summary["retrieved_records"]} retrieved; {summary["selected_records"]} selected; '
                      f'{len(summary["failed_years"])} failed year(s)')
            for warning in result.warnings:
                print('WARNING: ' + warning, file=sys.stderr)
            if args.email_to:
                print('Exploration report and attachments accepted by SMTP server')
            return 0
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    if args.command in ('collect', 'send'):
        try:
            if args.command == 'collect':
                from .digest import run_digest
                print(run_digest(args.config, args.out, stage='collect', retry_empty=args.retry_empty))
            else:
                from .digest import send_saved_digest
                print(send_saved_digest(args.out))
            return 0
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    if args.command == 'send-local':
        from .local_email import send_local
        try:
            print(send_local(args.papers, args.out, preview=args.preview, title=args.title))
            return 0
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    if args.command == 'digest':
        from .digest import run_digest, digest_recipient
        try:
            settings = json.loads(Path(args.config).read_text(encoding='utf-8'))
            recipient = digest_recipient(settings)
            required = [] if args.preview else [
                'SCOUT_SMTP_HOST', 'SCOUT_SMTP_USER', 'SCOUT_SMTP_PASSWORD', 'SCOUT_EMAIL_FROM']
            if not args.preview and not recipient:
                required.append('SCOUT_EMAIL_TO')
            missing = [key for key in required if not os.getenv(key)]
            if missing:
                raise ValueError('Missing local credentials: ' + ', '.join(missing) +
                                 '. Run python3 scripts/configure_credentials.py locally.')
            print(run_digest(args.config, args.out, preview=args.preview))
            return 0
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    if args.command == 'test':
        return subprocess.call([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'])
    if args.command == 'schedule':
        return subprocess.call([sys.executable, 'scripts/setup_schedule.py'])
    if args.command in ('preview', 'daily'):
        return scout_main(['daily', '--config', args.config, '--out', args.out] +
                          (['--preview'] if args.command == 'preview' else []))
    if args.command == 'check':
        from .research_profile import ResearchProfile
        try:
            for slug in TOPICS.values():
                ResearchProfile.load(f'config/profiles/{slug}.json')
                if scout_main(['validate-config', '--config', f'config/{slug}.json']):
                    return 1
        except (OSError, ValueError, TypeError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
        return 0
    if not os.getenv('OPENAI_API_KEY'):
        print('ERROR: Set OPENAI_API_KEY in .env before running research. Use check or test without a key.', file=sys.stderr)
        return 1
    topics = TOPICS if args.topic == 'all' else {args.topic: TOPICS[args.topic]}
    failures = []
    for alias, slug in topics.items():
        folder = Path(args.out) / slug
        print(f'Running {alias}: {folder}', flush=True)
        command = ['research', '--config', f'config/{slug}.json',
                   '--profile', f'config/profiles/{slug}.json', '--out', str(folder),
                   '--state', str(folder/'research-seen.json')]
        if args.no_verify:
            command.append('--no-verify')
        if args.text_manifest:
            command.extend(['--text-manifest', args.text_manifest])
        if scout_main(command):
            failures.append(alias)
    if failures:
        print('Failed topics: ' + ', '.join(failures) + '. Check errors above; successful reports were retained.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
