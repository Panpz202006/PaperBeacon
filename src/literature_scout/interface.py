"""Short commands for the repository workflow, with isolated topic histories."""
import argparse
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
    research = sub.add_parser('research', help='Generate research reports; no email or experiments')
    research.add_argument('topic', choices=['all', *TOPICS], nargs='?', default='all')
    research.add_argument('--out', default='runs/research', help='Parent directory for per-topic reports/history')
    research.add_argument('--no-verify', action='store_true')
    research.add_argument('--text-manifest')
    collect = sub.add_parser('collect', help='Stage 1: collect three-topic papers and save local files; no email')
    collect.add_argument('--config', default='config/daily_digest.json')
    collect.add_argument('--out', default='runs/daily-three-topics')
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
    if args.command in ('collect', 'send'):
        try:
            if args.command == 'collect':
                from .digest import run_digest
                print(run_digest(args.config, args.out, stage='collect'))
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
        from .digest import run_digest
        try:
            required = [] if args.preview else [
                'SCOUT_SMTP_HOST', 'SCOUT_SMTP_USER', 'SCOUT_SMTP_PASSWORD', 'SCOUT_EMAIL_FROM', 'SCOUT_EMAIL_TO']
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
