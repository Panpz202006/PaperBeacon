"""Stdlib HTTP with timeouts, bounded retries, and global per-host pacing."""
from __future__ import annotations
import json
import math
from email.utils import parsedate_to_datetime
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

LOG = logging.getLogger(__name__)

class AuthenticationError(RuntimeError):
    """Credentials rejected; repeated requests cannot repair them."""


class ResponseFormatError(RuntimeError):
    """Provider returned a non-JSON response; no response body is logged."""


class RateLimitError(RuntimeError):
    """A provider remains rate limited; stop submitting queries for this scan."""


def retry_after_seconds(value: str) -> float | None:
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


class HttpClient:
    def __init__(self, *, timeout: float = 20, max_retries: int = 2, sleep=time.sleep, defer_rate_limits=False):
        self.defer_rate_limits = defer_rate_limits
        self.timeout = timeout
        self.max_retries = max_retries
        self.sleep = sleep
        self.last_request: dict[str, float] = defaultdict(float)
        self.min_interval = {'export.arxiv.org': 3.0, 'api.openalex.org': 1.0,
                             'api.semanticscholar.org': 1.2, 'dblp.org': 1.0}

    def request(self, endpoint: str, params: dict | None = None, *, headers: dict | None = None,
                method: str = 'GET', payload: dict | None = None) -> bytes:
        qs = urllib.parse.urlencode(params or {}, doseq=True)
        url = endpoint + ('&' if '?' in endpoint else '?') + qs if qs else endpoint
        host = urllib.parse.urlparse(url).hostname or ''
        extra = f' (mailto:{os.environ.get("SCOUT_CONTACT_EMAIL")})' if os.environ.get('SCOUT_CONTACT_EMAIL') else ''
        request_headers = {'User-Agent': f'LiteratureScout/0.1 ({extra or "academic metadata research"})',
                           'Accept': 'application/json, application/atom+xml;q=0.9'}
        request_headers.update(headers or {})
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        if data is not None:
            request_headers['Content-Type'] = 'application/json'
        for attempt in range(self.max_retries + 1):
            # Rate limit every request to a host, including retry attempts.
            elapsed = time.monotonic() - self.last_request[host]
            gap = self.min_interval.get(host, 0.5)
            if elapsed < gap:
                self.sleep(gap - elapsed)
            self.last_request[host] = time.monotonic()
            try:
                req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and host == 'api.openai.com':
                    try:
                        error_info = json.loads(exc.read()).get('error', {})
                        quota_code = error_info.get('code') or error_info.get('type')
                    except (ValueError, AttributeError):
                        quota_code = None
                    if quota_code in ('insufficient_quota', 'billing_hard_limit_reached'):
                        raise RuntimeError('OpenAI API insufficient_quota: API billing/credits unavailable; automatic retries cannot resolve this') from None
                if exc.code in (401, 403):
                    raise AuthenticationError(f'{host} HTTP {exc.code}: credentials/access rejected') from None
                if exc.code in (500, 502, 503, 504) and self.defer_rate_limits:
                    error = RuntimeError(f'{host} HTTP {exc.code}; service unavailable, deferred')
                    error.retry_after = retry_after_seconds(exc.headers.get('Retry-After', '')) or 0
                    raise error from None
                if exc.code == 429 and self.defer_rate_limits:
                    delay = retry_after_seconds(exc.headers.get('Retry-After', '')) or 0
                    error = RateLimitError(f'{host} HTTP 429; deferred to persistent cooldown')
                    error.retry_after = delay
                    raise error from None
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise RuntimeError(f'{host} HTTP {exc.code} on {endpoint}') from exc
                delay = retry_after_seconds(exc.headers.get('Retry-After', ''))
                if delay is None:
                    delay = min(60, (5 if exc.code == 429 else 2) * 2 ** attempt)
                if exc.code == 429:
                    # Keep subsequent requests slower even after a successful retry.
                    self.min_interval[host] = min(60, self.min_interval.get(host, 0.5) * 2)
                    if attempt == self.max_retries or delay > 60:
                        hint = (' Set OPENALEX_API_KEY to your verified key or check your '
                                'OpenAlex quota.' if host == 'api.openalex.org' else '')
                        raise RateLimitError(
                            f'{host} HTTP 429: rate limit or quota exhausted; '
                            f'retry after {delay:.1f}s.{hint}'
                        ) from exc
                elif attempt == self.max_retries:
                    raise RuntimeError(f'{host} HTTP {exc.code} on {endpoint}') from exc
                LOG.warning('%s returned %s; retry in %.1fs', host, exc.code, delay)
                self.sleep(delay)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == self.max_retries:
                    raise RuntimeError(f'Network failure contacting {host}: {exc}') from exc
                self.sleep(min(20, 2 ** (attempt + 1)))
        raise RuntimeError('Request failed')

    def json(self, endpoint: str, params: dict | None = None, **kwargs):
        raw = self.request(endpoint, params, **kwargs)
        try:
            return json.loads(raw.decode('utf-8-sig'))
        except (ValueError, UnicodeError):
            host = urllib.parse.urlparse(endpoint).hostname
            raise ResponseFormatError(f'{host}: expected JSON; received an empty, HTML, or malformed response') from None
