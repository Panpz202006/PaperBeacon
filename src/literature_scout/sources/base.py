from __future__ import annotations
from typing import Protocol
from ..models import Paper
from ..http_client import HttpClient

class Source(Protocol):
    name: str
    def search(self, query: str, *, since: int, limit: int, client: HttpClient) -> list[Paper]: ...
