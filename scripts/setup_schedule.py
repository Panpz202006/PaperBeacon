#!/usr/bin/env python3
"""Generate a reviewable macOS LaunchAgent without touching the user Library."""
import argparse
from pathlib import Path
import plistlib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', default='runs/com.literature-scout.daily.plist')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
(root / 'runs').mkdir(exist_ok=True)
path = Path(args.out)
path.parent.mkdir(parents=True, exist_ok=True)
with path.open('wb') as stream:
    plistlib.dump({
        'Label': 'com.literature-scout.daily',
        'ProgramArguments': ['/bin/bash', str(root / 'scripts/daily_watch.sh')],
        'WorkingDirectory': str(root),
        'RunAtLoad': True,
        'StartInterval': 300,
        'StartCalendarInterval': {'Hour': 7, 'Minute': 30},
        'StandardOutPath': str(root / 'runs/daily.log'),
        'StandardErrorPath': str(root / 'runs/daily-error.log'),
        'ProcessType': 'Background',
    }, stream)
print(f'Generated {path.resolve()}')
