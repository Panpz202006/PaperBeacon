"""One durable email for all configured topics; at most five papers in total."""
from datetime import datetime, time
from email.utils import format_datetime
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .daily import run_daily, save_json, locked, plain_report, send_email, coverage_note, concise_papers
from .dedup import deduplicate
from .ranking import daily_ranker, ranking_text
from .models import Paper
from .monitor import identity_tokens
from .history import historical_shortlists


def digest_recipient(settings):
    """Resolve a private recipient override; fail closed instead of using another report's address."""
    key = settings.get('recipient_env')
    if key:
        value = os.getenv(key, '').strip()
        if not value:
            raise ValueError(f'Missing private recipient setting: {key}')
        return value
    return settings.get('recipient')


def finalize(folder, state, path):
    pending = state['pending']
    for child in pending['children']:
        child_folder = folder / child
        child_path = child_folder / 'daily-state.json'
        with locked(child_folder / '.daily.lock'):
            child_state = json.loads(child_path.read_text(encoding='utf-8'))
            child_state['reported'] = sorted(set(child_state['reported']) | set(pending['tokens']))
            child_state['deliveries'][pending['day']] = {'sent_at': pending['submitted_at'],
                                                        'message_id': pending['message_id']}
            child_state.pop('pending', None)
            save_json(child_path, child_state)
    state['reported'] = sorted(set(state['reported']) | set(pending['tokens']))
    if pending.get('replaces_empty_report') and pending['day'] in state['deliveries']:
        state.setdefault('superseded_empty_deliveries', []).append(
            {'day': pending['day'], **state['deliveries'][pending['day']]})
    state['deliveries'][pending['day']] = {'sent_at': pending['submitted_at'], 'message_id': pending['message_id']}
    (folder / f'paperbeacon-daily-{pending["day"]}.txt').write_text(pending['body'], encoding='utf-8')
    del state['pending']
    save_json(path, state)


def run_digest(manifest, folder, *, preview=False, now=None, prepare=run_daily,
               ranker=None, sender=send_email, stage='both', retry_empty=False):
    if stage not in ('both', 'collect'):
        raise ValueError('stage must be both or collect')
    manifest = Path(manifest).resolve()
    settings = json.loads(manifest.read_text(encoding='utf-8'))
    recipient = digest_recipient(settings)
    now = (now or datetime.now().astimezone()).astimezone(ZoneInfo(settings['timezone']))
    today = str(now.date())
    ranker = ranker or daily_ranker(settings)
    if now.time() < time.fromisoformat(settings['send_time']) and not preview and stage == 'both':
        return 'Waiting until ' + settings['send_time']
    configs = [(Path(item).stem, load_config(manifest.parent / item)) for item in settings['topics']]
    if not configs or len({slug for slug, _ in configs}) != len(configs):
        raise ValueError('Digest needs nonempty, uniquely named topic configs')
    for _, cfg in configs:
        cfg.update(timezone=settings['timezone'], send_time=settings['send_time'],
                   recovery_dir=str(Path(folder).resolve() / 'provider-recovery'),
                   retrieval_policy=settings.get('retrieval_policy', 'available'),
                   openalex_anonymous_fallback=settings.get('openalex_anonymous_fallback', True),
                   ranking_method=settings.get('ranking_method', 'keyword'))
        if cfg.get('abstract_file'):
            raise ValueError('Combined digest topics must specify topic text, not abstract_file')
    scope = hashlib.sha256(json.dumps(configs, sort_keys=True).encode()).hexdigest()
    folder = Path(folder).resolve()
    with locked(folder / '.digest.lock'):
        path = folder / 'digest-state.json'
        state = json.loads(path.read_text()) if path.exists() else {
            'scope': scope, 'reported': [], 'deliveries': {}}
        if state['scope'] != scope:
            raise ValueError('Combined research scope changed; choose a new digest output directory')
        if state.get('pending', {}).get('submitted_at') and not preview:
            finalize(folder, state, path)  # Complete local bookkeeping without resending.
        replacing = bool(state.get('pending', {}).get('replaces_empty_report'))
        if retry_empty and today in state['deliveries'] and not replacing:
            confirm_empty_report(folder, today)
        if today in state['deliveries'] and not preview and not retry_empty and not replacing:
            return 'Already sent today'
        if not state.get('pending') or preview:
            prepared = []
            unavailable = []
            for slug, cfg in configs:
                try:
                    item = prepare(cfg, cfg['topic'], folder / slug, now=now, preview=(preview or retry_empty),
                                   prepare_only=True, excluded_tokens=state['reported'])
                    if not isinstance(item, dict):
                        raise RuntimeError(f'no prepared report: {item}')
                    prepared.append((slug, cfg, item))
                except (OSError, ValueError, RuntimeError, KeyError) as exc:
                    unavailable.append(f'{cfg["name"]}: collection unavailable — {exc}')
            candidates = deduplicate([Paper.from_dict(p) for _, _, item in prepared for p in item['papers']])
            candidates = [p for p in candidates if not identity_tokens(p) & set(state['reported'])]
            topic_text = '\n'.join(ranking_text(cfg, cfg['topic']) for _, cfg in configs)
            selected = ranker(candidates, topic_text, settings['llm_model'])[:5]
            selection_mode = 'recent'
            history_issues = []
            if not selected and settings.get('historical_fallback', True):
                historical, history_issues = historical_shortlists(configs, folder, now.date(), state['reported'], ranker)
                historical_candidates = deduplicate([Paper.from_dict(p) for _, _, item in historical for p in item['papers']])
                selected = ranker(historical_candidates, topic_text, settings['llm_model'])[:5]
                if selected:
                    historical_slugs = {slug for slug, _, _ in historical}
                    prepared = historical + [entry for entry in prepared if entry[0] not in historical_slugs]
                    selection_mode = 'historical'
            if not prepared:
                raise RuntimeError('No current evidence or unreported historical recommendations available. ' + '; '.join(unavailable + history_issues))
            if retry_empty and not selected:
                raise RuntimeError('No unreported papers available; no replacement email prepared')
            label = settings.get('name', 'Anomaly Detection Research | Survival, GANs & Agentic AI')
            subject = f'{label} | {today} | {len(selected)} papers'
            lines = (["Historical picks — previously unreported papers from your saved library.", '']
                     if selection_mode == 'historical' else [])
            lines.append(topic_sections(configs, prepared, selected))
            pending = {'day': today, 'subject': subject, 'body': '\n'.join(lines),
                       'tokens': sorted(set().union(*(identity_tokens(p) for p in selected))),
                       'children': [slug for slug, _, _ in prepared],
                       'coverage_warnings': unavailable + history_issues,
                       'selection_mode': selection_mode,
                       'replaces_empty_report': bool(retry_empty and today in state['deliveries']),
                       'source_coverage': {slug: item.get('coverage_warnings', []) for slug, _, item in prepared},
                       'ranking_method': settings.get('ranking_method', 'keyword'),
                       'message_id': f'<scout.combined.{scope[:20]}.{today}@literature-scout.local>',
                       'date_header': format_datetime(now)}
            if recipient:
                pending['to'] = recipient
            if preview:
                (folder / 'preview.txt').write_text(pending['body'], encoding='utf-8')
                return f'Combined preview saved: {folder / "preview.txt"}; no email sent'
            archive = folder / 'collected' / today
            archive.mkdir(parents=True, exist_ok=True)
            for slug, cfg, item in prepared:
                save_json(archive / f'{slug}-daily-{today}-papers.json', item['papers'])
                (archive / f'{slug}-daily-{today}-report.txt').write_text(item['body'] if 'body' in item
                    else plain_report(cfg['name'], [Paper.from_dict(p) for p in item['papers']]), encoding='utf-8')
            save_json(archive / f'paperbeacon-daily-{today}-papers.json', [p.to_dict() for p in selected])
            (archive / f'paperbeacon-daily-{today}-report.txt').write_text(pending['body'], encoding='utf-8')
            save_json(archive / f'paperbeacon-daily-{today}-email.json', pending)
            pending['archive'] = str(archive)
            state['pending'] = pending
            save_json(path, state)
        if stage == 'collect':
            return f'Collection saved locally for {state["pending"]["day"]}; no email sent'
        return deliver_pending(folder, state, path, sender=sender, now=now)


def deliver_pending(folder, state, path, *, sender, now):
    pending = state['pending']
    sender(pending)
    pending['submitted_at'] = now.isoformat()
    save_json(path, state)
    day = pending['day']
    finalize(folder, state, path)
    return f'Sent one combined email for {day}'



def send_saved_digest(folder, *, sender=send_email, now=None):
    """Stage two: read prepared local state only; no discovery or GPT calls."""
    folder = Path(folder).resolve()
    now = now or datetime.now().astimezone()
    with locked(folder / '.digest.lock'):
        path = folder / 'digest-state.json'
        if not path.exists():
            return 'No collected digest found; run collect first'
        state = json.loads(path.read_text(encoding='utf-8'))
        if not state.get('pending'):
            return 'No unsent collected digest; no email sent'
        if state['pending'].get('submitted_at'):
            finalize(folder, state, path)
            return 'Previously accepted email finalized; not resent'
        return deliver_pending(folder, state, path, sender=sender, now=now)



def topic_sections(configs, prepared, selected):
    """Only populated topic sections in email; diagnostics stay in local metadata."""
    available = {slug: item for slug, _, item in prepared}
    short_titles = {
        'survival_continual': 'Survival & Continual Learning',
        'gan_continual': 'GANs & Continual Learning',
        'peft_agentic': 'Efficient Learning & AI Agents',
    }
    included = set()
    sections = []
    for slug, cfg in configs:
        item = available.get(slug)
        if item is None:
            continue
        tokens = set().union(*(identity_tokens(Paper.from_dict(p)) for p in item['papers']))
        papers = [p for p in selected if identity_tokens(p) & tokens and p.key not in included]
        included.update(p.key for p in papers)
        if not papers:
            continue
        heading = short_titles.get(slug, cfg['name'])
        sections.append(heading + '\n' + '─' * len(heading) + '\n\n' + concise_papers(papers))
    return '\n'.join(sections).strip() if sections else 'No new papers today.'



def confirm_empty_report(folder, day):
    """Require the original archived selection to prove a zero-paper delivery."""
    for prefix in ('paperbeacon-daily', 'anomaly-research'):
        path = folder / 'collected' / day / f'{prefix}-{day}-papers.json'
        if not path.exists():
            continue
        papers = json.loads(path.read_text(encoding='utf-8'))
        if papers != []:
            raise ValueError('Today’s report contained papers; --retry-empty cannot resend it')
        return
    raise ValueError('Cannot verify an archived zero-paper report; delivery history was not changed')
