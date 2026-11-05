"""Poll-and-diff monitor. Persist stable identities to avoid repeat notifications."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from .models import Paper, normalize_text


def identity_tokens(p: Paper) -> set[str]:
    ans = {'title:' + normalize_text(p.title)}
    if p.doi:
        ans.add('doi:' + p.doi)
    if p.arxiv_id:
        ans.add('arxiv:' + p.arxiv_id.casefold())
    return ans


def update_state(papers: list[Paper], *, state_file: Path, emit_first: bool = False) -> list[Paper]:
    first_run = not state_file.exists()
    if not first_run:
        prev = json.loads(state_file.read_text(encoding='utf-8'))
        old = set(prev.get('seen', []))
    else:
        old = set()
    new = [p for p in papers if not (identity_tokens(p) & old)]
    seen = old | set().union(*(identity_tokens(p) for p in papers)) if papers else old
    state_file.parent.mkdir(parents=True, exist_ok=True)
    # Atomic update avoids truncating state during interrupted write.
    temporary = state_file.with_suffix(state_file.suffix + '.tmp')
    temporary.write_text(json.dumps({'updated_utc': datetime.now(timezone.utc).isoformat(),
                                     'seen': sorted(seen)}, indent=2), encoding='utf-8')
    temporary.replace(state_file)
    return new if (emit_first or not first_run) else []


def new_papers_md(papers: list[Paper], *, initialized: bool = False) -> str:
    lines = ['# New literature matches', '',
             'This is a diff against previous observed identities. Relevance and venue labels remain provisional.', '']
    if initialized:
        lines += ['Baseline state initialized; existing papers were not reported as new.', '']
    if not papers and not initialized:
        lines += ['No newly observed matching records in this run.', '']
    for p in papers:
        lines.append(f'- [{p.title}]({p.url}) ({p.year or "?"}; {p.venue_canonical}; evidence: {p.venue_evidence})')
    lines.append('')
    return '\n'.join(lines)
