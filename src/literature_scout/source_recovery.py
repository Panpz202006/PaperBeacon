"""Persistent provider circuits and exact-query cache. Never store credentials."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import time
from .http_client import AuthenticationError, RateLimitError
from .models import Paper


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


class SourceRecovery:
    def __init__(self, root, source, *, clock=time.time):
        self.root = Path(root)
        self.source = source
        self.clock = clock
        self.path = self.root / (source + '.json')
        self.state = {}
        key = os.getenv({'openalex': 'OPENALEX_API_KEY', 'semantic_scholar': 'SEMANTIC_SCHOLAR_API_KEY'}.get(source, ''), '')
        self.fingerprint = hashlib.sha256(key.encode()).hexdigest()

    @contextmanager
    def session(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / (self.source + '.lock')).open('a') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            self.state = json.loads(self.path.read_text()) if self.path.exists() else {}
            if self.state.get('credential_fingerprint') != self.fingerprint:
                self.state = {'credential_fingerprint': self.fingerprint}
            try:
                yield True
            finally:
                atomic(self.path, self.state)

    def blocked(self):
        if self.state.get('auth_blocked'):
            return 'credentials rejected; waiting for credential change'
        if self.state.get('retry_at', 0) > self.clock():
            return f'cooldown: retry in {int(self.state["retry_at"] - self.clock())}s'
        return ''

    def fail(self, error):
        failures = min(self.state.get('failures', 0) + 1, 8)
        delay = min(86400, 900 * 2 ** (failures - 1))
        delay = max(delay, getattr(error, 'retry_after', 0))
        delay += random.uniform(0, 30)
        self.state.update(failures=failures, retry_at=self.clock() + delay,
                          error_type=type(error).__name__)
        if isinstance(error, AuthenticationError):
            self.state['auth_blocked'] = True

    def success(self):
        self.state.pop('auth_blocked', None)
        self.state.update(failures=0, retry_at=0, last_success=self.clock())

    def cache_path(self, options):
        digest = hashlib.sha256(json.dumps([self.source, options], sort_keys=True).encode()).hexdigest()
        return self.root / 'cache' / (digest + '.json')

    def cached(self, options):
        path = self.cache_path(options)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        if self.clock() - data['retrieved_at'] > 21600:
            return None
        return [Paper.from_dict(p) for p in data['papers']]

    def store(self, options, papers):
        atomic(self.cache_path(options), {'retrieved_at': self.clock(), 'papers': [p.to_dict() for p in papers]})


def recover_source(config, source, queries, adapter, client):
    """Return records, coverage warnings, fresh query count and cache query count."""
    recovery = SourceRecovery(config['recovery_dir'], source)
    papers, warnings = [], []
    fresh = cached_count = 0
    with recovery.session() as acquired:
        if not acquired:
            return [], [f'{source}: another process is accessing this source; skipped'], 0, 0
        for query in queries:
            options = {'query': query, 'since': config['since'], 'limit': config['per_source_per_query'],
                       'date_start': config.get('_date_start'), 'date_end': config.get('_date_end')}
            cached = recovery.cached(options)
            if cached is not None:
                papers.extend(cached)
                cached_count += 1
                continue
            blocked = recovery.blocked()
            if blocked:
                warnings.append(f'{source}: {blocked}; query deferred')
                continue
            kwargs = {'since': config['since'], 'limit': config['per_source_per_query'], 'client': client}
            if config.get('_date_start') and source in ('openalex', 'arxiv'):
                kwargs.update(date_start=config['_date_start'], date_end=config['_date_end'])
            if source == 'openalex' and recovery.state.get('anonymous_only'):
                kwargs['anonymous'] = True
            try:
                try:
                    found = adapter.search(query, **kwargs)
                except AuthenticationError:
                    if source != 'openalex' or not os.getenv('OPENALEX_API_KEY') or kwargs.get('anonymous') or not config.get('openalex_anonymous_fallback'):
                        raise
                    # Public endpoint only. Do not retry rejected credentials on later queries/runs.
                    recovery.state['anonymous_only'] = True
                    kwargs['anonymous'] = True
                    found = adapter.search(query, **kwargs)
                recovery.success()
                recovery.store(options, found)
                papers.extend(found)
                fresh += 1
            except (RuntimeError, ValueError, OSError, KeyError) as exc:
                recovery.fail(exc)
                warnings.append(f'{source}: {exc}; remaining uncached queries deferred')
        if recovery.state.get('anonymous_only'):
            warnings.append('openalex: configured credential rejected; public anonymous endpoint used (smaller budget)')
    return papers, warnings, fresh, cached_count
