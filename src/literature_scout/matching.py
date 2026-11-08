"""Dependency-free exploration matching: explicit concepts and BM25 lexical evidence."""
from collections import Counter
import math
import re
from .ranking import STOP

# Deliberately small, reviewable related-term sets, activated only by the user's query.
RELATED = {
    'survival analysis': ('survival analysis', 'survival', 'time to event', 'survival prediction',
                          'survival modeling', 'survival models'),
    'continual learning': ('continual learning', 'continual', 'lifelong learning', 'incremental learning',
                           'class incremental', 'task incremental', 'domain incremental', 'catastrophic forgetting'),
    'parameter efficient learning': ('parameter efficient learning', 'parameter efficient', 'peft',
                                     'adapter tuning', 'prompt tuning', 'prefix tuning',
                                     'low rank adaptation', 'lora'),
    'low rank': ('low rank', 'lowrank', 'low rank adaptation', 'lora'),
    'anomaly detection': ('anomaly detection', 'anomaly', 'anomalous', 'outlier detection', 'outlier', 'novelty detection'),
}
INFLECTIONS = {'anomalies': 'anomaly', 'outliers': 'outlier', 'hazards': 'hazard'}
GENERIC = {'analysis', 'detection', 'prediction', 'classification'}


def words(text):
    return [INFLECTIONS.get(w, w) for w in re.findall(r'[a-z][a-z0-9]*', text.casefold())]


def phrase_present(phrase, tokens):
    return ' ' + ' '.join(phrase) + ' ' in ' ' + ' '.join(tokens) + ' '


def query_topics(text):
    tokens = words(text)
    topics = [(name, [words(alias) for alias in aliases]) for name, aliases in RELATED.items()
              if any(phrase_present(words(alias), tokens) for alias in aliases)]
    # Commas/semicolons/"and" denote separate topics; prose within one topic supplies ranking context.
    for part in re.split(r'[,;\n]+|\band\b', text, flags=re.I):
        part_tokens = words(part)
        if not part_tokens or any(any(phrase_present(alias, part_tokens) for alias in aliases)
                                  for _, aliases in topics):
            continue
        informative = [w for w in part_tokens if w not in STOP and w not in GENERIC]
        if informative:
            topics.append((' '.join(part_tokens), [part_tokens]))
    return topics


def resolve_topic_weights(text, weights=None):
    """Accept a mapping or repeated TOPIC=WEIGHT arguments; never silently ignore a typo."""
    topics = query_topics(text)
    if not topics:
        raise ValueError('Provide at least one informative research topic')
    result = {name: 1.0 for name, _ in topics}
    entries = []
    if isinstance(weights, dict):
        entries = list(weights.items())
    elif weights is not None:
        if isinstance(weights, str):
            weights = [weights]
        for value in weights:
            if not isinstance(value, str) or '=' not in value:
                raise ValueError('Use --weight "topic=number"')
            entries.append(value.rsplit('=', 1))
    assigned = set()
    for label, value in entries:
        if not isinstance(label, str):
            raise ValueError('Weight topic names must be strings')
        normalized = words(label)
        exact = [name for name, _ in topics if words(name) == normalized]
        candidates = exact or [name for name, aliases in topics if normalized in aliases]
        if len(candidates) != 1:
            raise ValueError(f'Unknown or ambiguous weighted topic {label!r}; choose: ' + ', '.join(result))
        name = candidates[0]
        if name in assigned:
            raise ValueError(f'Duplicate weight for {name}')
        try:
            number = float(value)
        except (ValueError, TypeError):
            raise ValueError('Weights must be positive finite numbers') from None
        if isinstance(value, bool) or not math.isfinite(number) or number <= 0:
            raise ValueError('Weights must be positive finite numbers')
        result[name] = number
        assigned.add(name)
    return result


def rank_exploration(papers, text, *, match='any', weights=None):
    """Return the full corpus in relevance order, plus evidence for qualifying papers.

    Weights emphasize topic coverage, title evidence, and BM25. Dates only break ties.
    An empty matched_terms marks a paper ineligible under the requested match policy.
    """
    if match not in {'any', 'all'}:
        raise ValueError('match must be any or all')
    topics = query_topics(text)
    configured = resolve_topic_weights(text, weights)
    # Normalize to mean 1 so only relative weights matter; avoid overflow in large inputs.
    largest = max(configured.values())
    scaled = {name: value / largest for name, value in configured.items()}
    average = sum(scaled.values()) / len(scaled)
    topic_weights = {name: value / average for name, value in scaled.items()}
    original = set(words(text)) - STOP - GENERIC
    expanded = {w for _, aliases in topics for alias in aliases for w in alias} - STOP - GENERIC
    vocabulary = original | expanded
    word_weights = {word: max(topic_weights[name] for name, aliases in topics
                             if any(word in alias for alias in aliases)) for word in expanded}
    documents = [(words(p.title), words(p.abstract)) for p in papers]
    frequencies = Counter(w for title, abstract in documents for w in set(title + abstract) & vocabulary)
    size = len(papers)
    avg_title = sum(len(title) for title, _ in documents) / max(size, 1)
    avg_abstract = sum(len(abstract) for _, abstract in documents) / max(size, 1)

    def bm25(tokens, average):
        counts = Counter(tokens)
        score = 0.0
        for word in vocabulary & counts.keys():
            frequency = counts[word]
            idf = math.log(1 + (size - frequencies[word] + 0.5) / (frequencies[word] + 0.5))
            weight = 1.0 if word in original else 0.5
            weight *= word_weights.get(word, 1.0)
            score += weight * idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * len(tokens) / max(average, 1)))
        return score

    details = {}
    for paper, (title, abstract) in zip(papers, documents):
        topic_matches, title_topics, expressions = [], [], {}
        for name, aliases in topics:
            title_hits = [' '.join(alias) for alias in aliases if phrase_present(alias, title)]
            abstract_hits = [' '.join(alias) for alias in aliases if phrase_present(alias, abstract)]
            if name not in RELATED:
                # Arbitrary topics keep lexical recall, with specificity supplied by IDF weighting.
                informative = set(aliases[0]) - STOP - GENERIC
                title_hits = title_hits or sorted(informative & set(title))
                abstract_hits = abstract_hits or sorted(informative & set(abstract))
            if title_hits or abstract_hits:
                topic_matches.append(name)
                expressions[name] = {'title': title_hits, 'abstract': abstract_hits}
            if title_hits:
                title_topics.append(name)
        qualifies = bool(topic_matches) and (match == 'any' or len(topic_matches) == len(topics))
        lexical = 3 * bm25(title, avg_title) + bm25(abstract, avg_abstract)
        topic_weight = 10 * (len(topics) + 1)
        weighted_topics = sum(topic_weights[name] for name in topic_matches)
        weighted_titles = sum(topic_weights[name] for name in title_topics)
        paper.score = round(topic_weight * weighted_topics + 10 * weighted_titles + 9 * lexical / (1 + lexical), 6)
        paper.matched_terms = sorted({expression for hits in expressions.values()
                                     for location in hits.values() for expression in location}) if qualifies else []
        if qualifies:
            details[paper.key] = {'matched_topics': topic_matches, 'title_topics': title_topics,
                                  'expressions': expressions, 'score': paper.score,
                                  'weighted_topic_coverage': weighted_topics,
                                  'weighted_title_coverage': weighted_titles}
    ranked = sorted(papers, key=lambda p: (-p.score, -(p.year or 0), p.key))
    return ranked, details, [name for name, _ in topics]
