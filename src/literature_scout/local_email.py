"""Send existing local paper records independently of discovery and GPT."""
import csv
from datetime import datetime
from email.utils import format_datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from .daily import locked, save_json, plain_report, send_email
from .dedup import deduplicate
from .models import Paper
from .monitor import identity_tokens


def read_papers(paths):
    papers = []
    for value in paths:
        path = Path(value)
        if path.suffix.lower() == '.csv':
            with path.open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
        elif path.suffix.lower() == '.json':
            rows = json.loads(path.read_text(encoding='utf-8'))
        else:
            raise ValueError('Use a papers.csv or papers.json file')
        if not isinstance(rows, list):
            raise ValueError('Paper JSON must contain a list of records')
        for row in rows:
            row = dict(row)
            if not isinstance(row.get('title'), str) or not row['title'].strip():
                raise ValueError(f'{path}: paper title is required')
            row['year'] = int(row['year']) if row.get('year') else None
            row['score'] = float(row.get('score') or 0)
            for field in ('sources', 'matched_terms', 'authors', 'notes'):
                if isinstance(row.get(field), str):
                    row[field] = [x.strip() for x in row[field].split(',') if x.strip()]
            papers.append(Paper.from_dict(row))
    return deduplicate(papers)


def send_local(paths, folder, *, preview=False, sender=send_email, now=None, title=None):
    folder = Path(folder)
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    with locked(folder/'.local-email.lock'):
        path = folder/'local-email-state.json'
        state = json.loads(path.read_text()) if path.exists() else {'reported': [], 'deliveries': []}
        if not state.get('pending') or preview:
            papers = [p for p in read_papers(paths) if not identity_tokens(p) & set(state['reported'])][:5]
            if not papers:
                return 'No unreported local papers; no email sent'
            label = title or ', '.join(dict.fromkeys(Path(p).parent.name.replace('_', ' ').replace('-', ' ') for p in paths))
            subject = f'{label} | Saved Literature | {now.date()} | {len(papers)} papers'
            body = plain_report(subject, papers, note=(
                'Source files: ' + ', '.join(str(Path(p)) for p in paths) + '\n'
                'Previously saved records; not a fresh seven-day search. Publication metadata is unverified.\n'
                'Up to five unreported papers in file order; no new GPT ranking was performed.'))
            fingerprint = hashlib.sha256(body.encode()).hexdigest()
            pending = {'subject': subject, 'body': body,
                       'tokens': sorted(set().union(*(identity_tokens(p) for p in papers))),
                       'message_id': f'<scout.local.{fingerprint[:32]}@literature-scout.local>',
                       'date_header': format_datetime(now)}
            if preview:
                (folder/'preview.txt').write_text(body, encoding='utf-8')
                return f'Local email preview saved: {folder / "preview.txt"}'
            state['pending'] = pending
            save_json(path, state)
        pending = state['pending']
        sender(pending)
        state['reported'] = sorted(set(state['reported']) | set(pending['tokens']))
        state['deliveries'].append({'sent_at': now.isoformat(), 'message_id': pending['message_id']})
        del state['pending']
        save_json(path, state)
        (folder/'last-email.txt').write_text(pending['body'], encoding='utf-8')
        return 'Local paper email accepted by SMTP server'
