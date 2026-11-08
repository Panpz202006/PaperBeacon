"""Durable daily digest, independent of scheduler uptime."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, formataddr
import fcntl
import hashlib
import json
import os
from pathlib import Path
import smtplib
import ssl
from zoneinfo import ZoneInfo

from .models import Paper
from .monitor import identity_tokens
from .pipeline import run_scan
from .ranking import daily_ranker, ranking_text


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


@contextmanager
def locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another daily run is already active') from None
        yield


def in_window(paper: Paper, start: date, end: date) -> bool:
    try:
        published = date.fromisoformat(paper.published[:10])
    except (ValueError, TypeError):
        return False  # A year alone cannot establish eligibility.
    return start <= published <= end


def plain_report(title: str, papers: list[Paper], *, note: str = '') -> str:
    lines = [title, '', note, '']
    if not papers:
        lines += ['No new qualifying papers today.', '']
    for i, p in enumerate(papers, 1):
        lines += [f'Paper {i}. {p.title}', '-' * 60,
                  f'Published in: {p.venue_canonical or p.venue_raw or "Unknown"}',
                  f'Publication date: {p.published or "Unknown"}', '',
                  'Selected authors & paper affiliations:']
        # Display order, not inferred importance or seniority.
        authors = list(dict.fromkeys(p.authors[:3] + [name for name in p.authors
                    if 'corresponding' in p.author_roles.get(name, [])]))
        if not authors:
            lines.append('  Not available from source metadata.')
        for author in authors:
            roles = p.author_roles.get(author, [])
            role_label = ' [' + ', '.join(roles) + ']' if roles else ''
            affiliations = '; '.join(p.author_affiliations.get(author, [])) or 'Affiliation not available from source metadata'
            lines.append(f'  - {author}{role_label}: {affiliations}')
        if len(authors) < len(p.authors):
            lines.append(f'  {len(p.authors)} authors total; showing first three plus explicitly marked corresponding authors.')
        if p.affiliation_sources:
            lines.append('  Affiliation metadata: ' + ', '.join(p.affiliation_sources))
        lines += ['', 'Abstract:', p.abstract or 'Not available from the source', '',
                  'Links:', f'  Download: {p.pdf_url or "No direct download available"}',
                  f'  Paper page: {p.url or "Not available"}']
        if p.matched_terms:
            lines += ['', f'Keyword relevance score: {p.score}',
                      'Matched terms: ' + ', '.join(p.matched_terms)]
        lines.append('')
    return '\n'.join(lines)


def send_email(message: dict) -> None:
    required = ('SCOUT_SMTP_HOST', 'SCOUT_EMAIL_FROM')
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise ValueError('Missing email settings: ' + ', '.join(missing))
    recipients = [x.strip() for x in message.get('to', os.getenv('SCOUT_EMAIL_TO', '')).split(',') if x.strip()]
    if not recipients:
        raise ValueError('SCOUT_EMAIL_TO needs at least one address')
    msg = EmailMessage()
    msg['Subject'] = message['subject']
    msg['From'] = (formataddr((os.environ['SCOUT_EMAIL_NAME'], os.environ['SCOUT_EMAIL_FROM']))
                   if os.getenv('SCOUT_EMAIL_NAME') else os.environ['SCOUT_EMAIL_FROM'])
    msg['To'] = ', '.join(recipients)
    msg['Message-ID'] = message['message_id']
    msg['Date'] = message['date_header']
    msg.set_content(message['body'])
    for attachment in message.get('attachments', []):
        file = Path(attachment)
        msg.add_attachment(file.read_bytes(), maintype='application', subtype='octet-stream', filename=file.name)
    mode = os.getenv('SCOUT_SMTP_SECURITY', 'starttls')
    if mode not in ('ssl', 'starttls'):
        raise ValueError('SCOUT_SMTP_SECURITY must be ssl or starttls')
    port = int(os.getenv('SCOUT_SMTP_PORT', '465' if mode == 'ssl' else '587'))
    context = ssl.create_default_context()
    smtp_type = smtplib.SMTP_SSL if mode == 'ssl' else smtplib.SMTP
    kwargs = {'context': context} if mode == 'ssl' else {}
    with smtp_type(os.environ['SCOUT_SMTP_HOST'], port, timeout=60, **kwargs) as smtp:
        if mode == 'starttls':
            smtp.starttls(context=context)
        if os.getenv('SCOUT_SMTP_USER'):
            smtp.login(os.environ['SCOUT_SMTP_USER'], os.environ['SCOUT_SMTP_PASSWORD'])
        refused = smtp.send_message(msg, to_addrs=recipients)
        if refused:
            raise RuntimeError('SMTP refused one or more recipients; inspect delivery before retrying')


def run_daily(config: dict, research_text: str, folder: Path, *, now: datetime | None = None,
              preview: bool = False, prepare_only: bool = False, excluded_tokens=(),
              scanner=run_scan, ranker=None, sender=send_email) -> str:
    ranker = ranker or daily_ranker(config)
    selection_text = ranking_text(config, research_text)
    ranking_label = ('Local keyword relevance (title 70%, abstract 30%; date breaks ties)'
                     if config.get('ranking_method', 'keyword') == 'keyword'
                     else os.getenv('SCOUT_LLM_MODEL', config['llm_model']))
    now = (now or datetime.now().astimezone()).astimezone(ZoneInfo(config['timezone']))
    today = now.date()
    hour, minute = map(int, config['send_time'].split(':'))
    if now.time() < time(hour, minute) and not preview and not prepare_only:
        return 'Waiting until ' + config['send_time']
    # Include search settings so a changed topic cannot silently reuse an old baseline.
    scope = {key: config[key] for key in ('venues', 'include_arxiv', 'sources', 'queries', 'venue_aliases')}
    fingerprint = hashlib.sha256(json.dumps([research_text, scope], sort_keys=True).encode()).hexdigest()
    folder = folder.resolve()
    with locked(folder / '.daily.lock'):
        path = folder / 'daily-state.json'
        state = json.loads(path.read_text()) if path.exists() else {
            'scope': fingerprint, 'reported': [], 'deliveries': {}, 'baseline': False}
        if state['scope'] != fingerprint:
            raise ValueError('Topic/search scope changed: use a new --out directory for its baseline')
        if str(today) in state['deliveries'] and not preview:
            return 'Already sent today'
        if state.get('pending') and not preview:
            pending = state['pending']
        else:
            try:
                year_start = today.replace(year=today.year - 1)
            except ValueError:
                year_start = today.replace(year=today.year - 1, day=28)
            start = year_start if not state['baseline'] else today - timedelta(days=6)
            cfg = {**config, 'since': start.year, '_date_start': start.isoformat(), '_date_end': today.isoformat()}
            result = scanner(cfg, research_text)
            check_retrieval(result, config)
            coverage = list(result.warnings)
            papers = [p for p in result.papers if in_window(p, start, today)]
            if not preview:
                save_json(folder / f'candidates-{start}-{today}.json', [p.to_dict() for p in papers])
                (folder / f'candidates-{start}-{today}.txt').write_text(plain_report(
                    config['name'] + f' | Retrieved candidates | {start} to {today}', papers,
                    note='Saved before final ranking; these are candidates, not a final shortlist.\n' + coverage_note(coverage)), encoding='utf-8')
                save_json(folder / f'coverage-{start}-{today}.json',
                          {'counts': result.counts, 'warnings': result.warnings, 'queries': result.queries})
            if not state['baseline']:
                baseline = ranker(papers, selection_text, config['llm_model'], baseline=True)
                if not preview:
                    save_json(folder / 'baseline-candidates.json', [p.to_dict() for p in papers])
                    save_json(folder / 'baseline.json', [p.to_dict() for p in baseline])
                    (folder / 'baseline.txt').write_text(plain_report(
                        'Initial one-year SOTA candidates', baseline,
                        note='Ranking: ' + ranking_label + '; verify SOTA claims against full papers.\n' + coverage_note(result.warnings)), encoding='utf-8')
                    state['baseline'] = True
                    state['baseline_coverage_warnings'] = result.warnings
                    save_json(path, state)
                # Search the week separately: yearly result caps must not hide recent papers.
                window_start = today - timedelta(days=6)
                recent_scan = scanner({**config, 'since': window_start.year,
                                  '_date_start': window_start.isoformat(), '_date_end': today.isoformat()},
                                 research_text)
                check_retrieval(recent_scan, config)
                coverage.extend(recent_scan.warnings)
                papers = recent_scan.papers
                if not preview:
                    save_json(folder / f'candidates-{window_start}-{today}.json', [p.to_dict() for p in papers])
            eligible = [p for p in papers if in_window(p, today - timedelta(days=6), today)
                        and not identity_tokens(p).intersection(set(state['reported']) | set(excluded_tokens))]
            ranked = ranker(eligible, selection_text, config['llm_model'])[:5]
            subject = f'{config["name"]}: academic digest — {today}'
            pending = {'day': str(today), 'subject': subject,
                       'papers': [p.to_dict() for p in ranked],
                       'coverage_warnings': list(dict.fromkeys(coverage)),
                       'body': plain_report(subject, ranked, note=f'Topic: {research_text}\nRanked by: {ranking_label}\n' + coverage_note(coverage)),
                       'tokens': sorted(set().union(*(identity_tokens(p) for p in ranked))),
                       'message_id': f'<scout.{fingerprint[:20]}.{today}@literature-scout.local>',
                       'date_header': format_datetime(now)}
            if preview:
                if prepare_only:
                    return pending
                (folder / 'preview.txt').write_text(pending['body'], encoding='utf-8')
                return 'Preview saved; no email sent or delivery state advanced'
            state['pending'] = pending
            save_json(path, state)
        if prepare_only:
            return pending
        # Retry the exact prepared report after failures, even across a restart.
        sender(pending)
        state['reported'] = sorted(set(state['reported']) | set(pending['tokens']))
        state['deliveries'][pending['day']] = {'sent_at': now.isoformat(), 'message_id': pending['message_id']}
        del state['pending']
        save_json(path, state)
        (folder / f'paperbeacon-daily-{pending["day"]}.txt').write_text(pending['body'], encoding='utf-8')
        return f'Sent report for {pending["day"]}'



def coverage_note(warnings):
    if not warnings:
        return 'Coverage: configured searches completed (indexing and retrieval limits still apply).'
    return 'PARTIAL COVERAGE — results from available sources only; absence of papers is not proof of no new work.\n' + '\n'.join(dict.fromkeys(warnings))


def check_retrieval(result, config):
    if config.get('retrieval_policy', 'strict') == 'strict':
        if result.warnings:
            raise RuntimeError('Incomplete retrieval; retry later: ' + '; '.join(result.warnings))
    elif not result.papers and not (result.counts.get('successful_queries', 0) or result.counts.get('cached_queries', 0)):
        raise RuntimeError('All sources unavailable and no usable cached evidence; collection deferred')


def concise_papers(papers):
    """Reader-facing cards; detailed scores and provenance remain in local records."""
    lines = []
    for index, paper in enumerate(papers, 1):
        lines += [f'{index}. {paper.title}',
                  f'{paper.venue_canonical or paper.venue_raw or "Venue unavailable"} | {paper.published or "Date unavailable"}']
        authors = list(dict.fromkeys(paper.authors[:3] + [name for name in paper.authors
                       if 'corresponding' in paper.author_roles.get(name, [])]))
        if authors:
            if any(paper.author_affiliations.get(name) for name in authors):
                for name in authors:
                    role = ' (corresponding)' if 'corresponding' in paper.author_roles.get(name, []) else ''
                    affiliations = '; '.join(paper.author_affiliations.get(name, []))
                    lines.append(f'{name}{role} — {affiliations or "affiliation unavailable"}')
            else:
                names = [name + (' (corresponding)' if 'corresponding' in paper.author_roles.get(name, []) else '')
                         for name in authors]
                lines += ['Authors: ' + ', '.join(names), 'Affiliations: unavailable']
            if len(authors) < len(paper.authors):
                lines.append(f'+ {len(paper.authors) - len(authors)} other authors')
        else:
            lines.append('Authors unavailable')
        lines += ['', 'Abstract', paper.abstract or 'Abstract unavailable', '']
        if paper.pdf_url:
            lines.append('PDF: ' + paper.pdf_url)
        if paper.url:
            lines.append('Paper: ' + paper.url)
        lines.append('')
    return '\n'.join(lines)
