# Architecture

PaperBeacon keeps the `literature_scout` module and original command names for compatibility.

## Daily workflow

`scripts/daily_watch.sh` is the combined daily scheduler entry point. `interface.py` exposes the repository commands through `scripts/scout.sh`. `digest.py` coordinates per-topic collection and a single durable email. `daily.py` manages yearly baselines, rolling seven-day discovery windows for daily delivery and paper cards. `ranking.py` supplies local keyword relevance; `dedup.py` links DOI, arXiv and normalized-title identities.

`pipeline.py` orchestrates OpenAlex, Semantic Scholar, DBLP and arXiv adapters. `http_client.py` handles HTTP errors and pacing; `source_recovery.py` persists provider circuits and exact-query caches. `models.py` stores bibliographic provenance and paper-specific author affiliations. `local_email.py` supports independent delivery of existing records.

Publication metadata is not proof of acceptance or research quality. Full publication dates are needed for daily eligibility. Indexed metadata can be incomplete or wrong; source limits and indexing lag can omit relevant work.

## Optional scientific analysis

Research profiles live under `config/profiles/`. `research.py` coordinates query planning, recent/foundational retrieval, independent registry checks, extraction, theory audit, idea generation, ranking and report export. Components are split across `research_profile`, `query_planner`, `paper_retriever`, `venue_verifier`, `paper_analyzer`, `theory_analyzer`, `novelty_analyzer`, `idea_generator`, `research_ranker`, `report_generator` and `research_monitor`.

Claims distinguish source-supported statements, interpretations, proposals and unknown information. Quote matching and stable paper identifiers establish traceability; they do not establish entailment, mathematical correctness or proven novelty. The experimental handoff always requires human approval.

Optional full-text analysis accepts a JSON manifest mapping exact `Paper.key` values to local UTF-8 text files. Pass `--text-manifest` to the original `literature-scout research` CLI. It records hashes and evidence levels. Supplied text is sent to the configured LLM; only use material you may share. Automatic PDF downloading and parsing are not implemented.

## Development

```bash
bash scripts/scout.sh check
bash scripts/scout.sh test
```

Tests use synthetic data and mocked HTTP/SMTP/LLM responses. Do not add network-dependent tests or real credentials. Configuration examples should use placeholders rather than personal addresses or local paths.

Add a source adapter returning `Paper` records, register it in `pipeline.SOURCES`, and test parsing, error classification and provenance. Avoid substituting author-profile institutions for the affiliations recorded on a particular paper.

## Future work

- Official proceedings/decision verification beyond registry alignment.
- Lawful PDF acquisition, extraction and section/page-level provenance.
- Optional local semantic ranking and user feedback on relevance.
- Explicit baseline refresh and longer-outage catch-up policies.

Keep the two-stage collection/delivery boundary and stable delivery history when extending the system. No multi-agent orchestration is required for the current workflow.
