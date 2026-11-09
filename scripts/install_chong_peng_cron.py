#!/usr/bin/env python3
"""Generate or install Professor Chong Peng's independent daily cron job."""
import argparse
from datetime import datetime
from pathlib import Path
import shlex
import subprocess
import tempfile
from zoneinfo import ZoneInfo

BEGIN = '# BEGIN PaperBeacon chong-peng daily report'
END = '# END PaperBeacon chong-peng daily report'


def job_block(root):
    def quote(path):
        return shlex.quote(str(path)).replace('%', r'\%')
    return '\n'.join([
        BEGIN,
        '# One daily report after 08:00 Asia/Shanghai; five-minute recovery checks.',
        '*/5 * * * * /bin/bash ' + quote(root/'scripts/chong_peng_daily.sh')
        + ' >> ' + quote(root/'runs/chong-peng-daily.log')
        + ' 2>> ' + quote(root/'runs/chong-peng-daily-error.log'),
        END,
    ]) + '\n'


def build_crontab(existing, root):
    block = job_block(root)
    if BEGIN not in existing and END not in existing:
        return existing.rstrip('\n') + ('\n\n' if existing.strip() else '') + block
    lines = existing.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip('\r\n') == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.rstrip('\r\n') == END]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError('Invalid or duplicate managed cron markers; existing crontab was not changed')
    return ''.join(lines[:starts[0]]) + block + ''.join(lines[ends[0]+1:])


def read_crontab():
    result = subprocess.run(['/usr/bin/crontab', '-l'], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 1 and 'no crontab for' in result.stderr:
        return ''
    raise RuntimeError('Cannot read crontab: ' + result.stderr.strip())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true', help='Install the job, preserving other entries; default: generate only')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    (root/'runs').mkdir(exist_ok=True)
    generated = root/'runs/chong-peng-cron.txt'
    generated.write_text(job_block(root), encoding='utf-8')
    if not args.install:
        print(f'Generated {generated}; use --install to activate')
        return 0
    existing = read_crontab()
    replacement = build_crontab(existing, root)
    if replacement == existing:
        print('Professor Chong Peng cron job is already installed')
        return 0
    backup_folder = root/'runs/scheduler-backups'
    backup_folder.mkdir(exist_ok=True)
    stamp = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S-%f')
    backup = backup_folder/f'crontab-before-chong-peng-{stamp}.txt'
    backup.write_text(existing, encoding='utf-8')
    if read_crontab() != existing:
        raise RuntimeError('Crontab changed during installation; retry to preserve the latest entries')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cron', encoding='utf-8') as stream:
        stream.write(replacement)
        stream.flush()
        subprocess.run(['/usr/bin/crontab', stream.name], check=True)
    if read_crontab() != replacement:
        raise RuntimeError('Installed crontab did not match the generated configuration; inspect crontab -l')
    print('Installed Professor Chong Peng daily report: 08:00 Asia/Shanghai, with five-minute recovery checks')
    print(f'Previous crontab saved: {backup}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
