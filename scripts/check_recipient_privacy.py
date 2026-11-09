#!/usr/bin/env python3
"""Reject plaintext personal email addresses in tracked content and new commit identities.

Only locations are printed, never the matched address. This is a plaintext guard,
not a guarantee against encoded addresses or historical exposures.
"""
import argparse
from pathlib import Path
import re
import subprocess

EMAIL = re.compile(rb"[A-Za-z0-9.!#$%&*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PUBLIC_DOMAINS = {'example.com', 'example.org', 'example.net', 'literature-scout.local',
                  'users.noreply.github.com', 'noreply.github.com'}


def is_private(address):
    address = address.strip(b"'")
    domain = address.rsplit(b'@', 1)[-1].decode('ascii').lower()
    if address.lower() == b'noreply@github.com':
        return False
    return not (domain in PUBLIC_DOMAINS or domain.endswith(('.example.com', '.example.org', '.example.net',
                                                      '.test', '.invalid')))


def audit_tracked_files(root, *, staged=False):
    paths = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z']).split(b'\0')
    findings = []
    for item in paths:
        if not item:
            continue
        path = item.decode('utf-8')
        if staged:
            # Deleted files are absent from the index; git ls-files already omits them.
            content = subprocess.check_output(['git', '-C', str(root), 'show', ':' + path])
        else:
            file = root/path
            if not file.is_file():
                continue
            content = file.read_bytes()
        for line_number, line in enumerate(content.splitlines(), 1):
            if any(is_private(match.group()) for match in EMAIL.finditer(line)):
                findings.append(f'{path}:{line_number}: non-placeholder email address')
    return findings


def audit_identity(root):
    findings = []
    for role in ('AUTHOR', 'COMMITTER'):
        result = subprocess.run(['git', '-C', str(root), 'var', f'GIT_{role}_IDENT'],
                                capture_output=True)
        if result.returncode:
            findings.append(f'Git {role.lower()} identity is not configured')
            continue
        address = re.search(rb'<([^>]+)>', result.stdout)
        if address and is_private(address.group(1)):
            findings.append(f'Git {role.lower()} uses a personal email; configure a public noreply identity')
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='Inspect the exact Git index instead of working files')
    args = parser.parse_args(argv)
    root = Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip())
    findings = audit_tracked_files(root, staged=args.staged) + audit_identity(root)
    for finding in findings:
        print(finding)
    if findings:
        print('Privacy check failed. Keep real addresses in ignored local files and use a public commit identity.')
        return 1
    print('Privacy check passed: tracked content and current commit identities contain no detected personal email addresses.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
