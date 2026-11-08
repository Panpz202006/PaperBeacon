# PaperBeacon

Discover research papers, rank them locally, and receive daily email reports. Python 3.11+; local matching uses only the standard library and needs no OpenAI key.

## Install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

## Search papers

Search keywords or a short description within selected venues and publication years:

```bash
bash scripts/scout.sh search \
  --topic "survival analysis, continual learning, parameter efficient learning, low-rank and anomaly detection" \
  --venues ICML,NIPS,ICLR \
  --since 2023 --until 2026 --top 100 \
  --out runs/my-search
```

Supported venues: **NeurIPS/NIPS, ICML, ICLR, AAAI, ACM MM, CVPR, IJCAI**. Omit `--venues` to search all seven.

Useful options:

- `--weight "survival analysis=3"`: emphasize a topic; repeat for other topics. Default weight: `1`.
- `--match all`: require evidence for every topic; default: any topic.
- `--from-run runs/my-search`: rerank a saved corpus without network requests.
- `--email-to researcher@example.org`: email the report and data attachments using configured SMTP.

Reports list **paper name, year, and venue**. A timestamped report and structured data are saved in the output directory. Matching uses topic phrases, related terms, and local word relevance. Check `coverage.json` for missing sources or years; results do not guarantee every accepted paper was found.

## Daily reports

Customize topics in `config/daily_digest.json` and its referenced topic files. Configure email once:

```bash
cp .env.example .env
chmod 600 .env
python3 scripts/configure_credentials.py --email-only
```

Collect and send separately:

```bash
bash scripts/scout.sh collect   # Retrieve, rank, and save locally
bash scripts/scout.sh send      # Send the saved report
```

Daily reports contain up to five previously unreported papers. When the recent selection is empty, saved historical recommendations can be included and labeled. Delivery history supports duplicate protection and recovery.

For automatic delivery on macOS, run `python3 scripts/install_schedule.py`. The default delivery time is **07:30 Asia/Shanghai**; the laptop must be awake and online.

## Documentation

- [Usage guide](docs/USAGE.md): weighted searches, email setup, scheduling, recovery, and optional research analysis.
- [Architecture](docs/ARCHITECTURE.md): internals and extension points.
- Run `bash scripts/scout.sh --help` for commands or `bash scripts/scout.sh test` for offline tests.

[MIT License](LICENSE).
