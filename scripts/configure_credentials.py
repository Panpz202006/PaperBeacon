#!/usr/bin/env python3
"""Enter credentials locally without echoing or printing them."""
import argparse
import getpass
import os
from pathlib import Path
import re
import shlex

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--email-only', action='store_true', help='Update only the Gmail app password')
args = parser.parse_args()

path = Path(__file__).resolve().parents[1] / '.env'
text = path.read_text(encoding='utf-8') if path.exists() else ''
prompts = [('SCOUT_SMTP_PASSWORD', 'Gmail app password for the configured sender (Enter keeps existing): ')]
if not args.email_only:
    prompts.insert(0, ('OPENAI_API_KEY', 'OpenAI API key (Enter keeps existing): '))
for key, prompt in prompts:
    value = getpass.getpass(prompt).strip()
    if not value:
        continue
    if key == 'SCOUT_SMTP_PASSWORD':
        value = value.replace(' ', '')
    line = key + '=' + shlex.quote(value)
    pattern = rf'(?m)^{key}=.*$'
    text = re.sub(pattern, lambda _: line, text) if re.search(pattern, text) else text + '\n' + line + '\n'
# Create securely; secrets never appear in shell arguments or tool output.
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.fchmod(fd, 0o600)
with os.fdopen(fd, 'w', encoding='utf-8') as stream:
    stream.write(text)
print('Saved local credentials in .env (permissions 600). No email sent.')
