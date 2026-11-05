"""Research interests separate from retrieval and transport configuration."""
from dataclasses import dataclass, field
import json
from pathlib import Path


@dataclass
class ResearchProfile:
    name: str
    topic: str
    bridges: list[str] = field(default_factory=list)
    foundations: list[str] = field(default_factory=list)
    modalities: list[str] = field(default_factory=lambda: ['computer vision', 'time series'])
    recent_days: int = 365
    foundation_since: int = 1900
    max_queries: int = 8
    max_analysis_papers: int = 30
    max_ideas: int = 4
    contact: str = ''  # Local reports only; never included in external requests.

    @classmethod
    def load(cls, path):
        obj = json.loads(Path(path).read_text(encoding='utf-8'))
        profile = cls(**obj)
        for key in ('name', 'topic'):
            if not isinstance(getattr(profile, key), str) or not getattr(profile, key).strip():
                raise ValueError(f'Profile {key} must be nonempty text')
        if not isinstance(profile.contact, str):
            raise ValueError('Profile contact must be text')
        for key in ('bridges', 'foundations', 'modalities'):
            if not isinstance(getattr(profile, key), list) or any(
                    not isinstance(x, str) or not x.strip() for x in getattr(profile, key)):
                raise ValueError(f'Profile {key} must contain nonempty strings')
        for key in ('recent_days', 'max_queries', 'max_analysis_papers', 'max_ideas'):
            value = getattr(profile, key)
            if type(value) is not int or not 1 <= value <= 1000:
                raise ValueError(f'Profile {key} must be an integer from 1 to 1000')
        if type(profile.foundation_since) is not int or not 1900 <= profile.foundation_since <= 2100:
            raise ValueError('foundation_since must be a year from 1900 to 2100')
        return profile

    def scientific_context(self):
        return {key: getattr(self, key) for key in ('name', 'topic', 'bridges', 'foundations', 'modalities')}
