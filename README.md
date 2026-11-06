# PaperBeacon

**Your daily signal from research.**

PaperBeacon is a configurable academic paper discovery and monitoring agent. Define your research topics, search queries, and preferred publication venues; PaperBeacon retrieves relevant papers, saves them locally, and delivers a concise daily email digest.

Lightweight keyword ranking runs entirely on your laptop, so daily monitoring requires no OpenAI API key or model download. Each paper entry includes its title, publication venue and date, available author affiliations, abstract, and download links. Persistent delivery tracking helps prevent duplicate reports and recover from interruptions.

Use PaperBeacon for a single research question or multiple research directions. The included topic configurations are examples you can adapt to your own interests, within the coverage of the supported academic sources.

The Python package and CLI retain their original names, `literature_scout` and `literature-scout`, for compatibility.

## Quick start

Requires Python 3.11+ on macOS or Linux. Runtime code uses only the Python standard library.

```bash
cd /path/to/PaperBeacon
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
chmod 600 .env
```

Edit `.env` locally. Set your SMTP host, port, security mode, login, sender address, display name and recipient. For Gmail, use `smtp.gmail.com`, port `587`, `starttls`, and an app password belonging to the sender account. `SCOUT_EMAIL_NAME='PaperBeacon'` controls the From display name. See [Google's app-password instructions](https://support.google.com/accounts/answer/185833).

Enter the email password privately in your terminal:

```bash
python3 scripts/configure_credentials.py --email-only
```

The script does not echo the password and saves `.env` with permissions `600`. Do not commit credentials. OpenAlex and Semantic Scholar API keys are optional provider credentials, separate from both Gmail and OpenAI credentials.

Validate configuration and run the offline tests:

```bash
bash scripts/scout.sh check
bash scripts/scout.sh test
```

The wrapper loads `.env` and selects `.venv/bin/python`, then the legacy `prcg/bin/python`, then `python3`. Override with `SCOUT_PYTHON` if needed. Direct Python CLI commands use your existing shell environment and do not load `.env` automatically.

## Two-stage daily workflow

```bash
# 1. Retrieve, rank locally, and save. Does not send email.
bash scripts/scout.sh collect

# 2. Send the saved digest. No academic API or GPT requests.
bash scripts/scout.sh send
```

For a combined due-time check, or a preview:

```bash
bash scripts/scout.sh digest
bash scripts/scout.sh digest --preview
bash scripts/scout.sh --help
```

A new topic first builds a baseline from the preceding year. Subsequent runs search the current seven-calendar-day window. Each topic produces a shortlist; the combined shortlist deduplicates across topics and includes at most five previously unreported papers total. Selection does not guarantee a fixed number from every topic.

Keyword relevance weights title matches at 70% and abstract matches at 30%. Dates break ties; papers without keyword matches are excluded. Edit `ranking_keywords` in the topic configurations to refine the vocabulary. Scores measure relevance, not scientific quality or verified SOTA performance.

The subject identifies research scope, date and paper count. The body contains only populated topic sections, with paper titles, venues, dates, authors, available affiliations, abstracts and links. It omits ranking explanations and operational logs. Selected authors are the first three in byline order plus explicitly marked corresponding authors. Affiliations come from paper metadata; missing affiliations are labeled rather than inferred.

## Configuration

The combined workflow reads `config/daily_digest.json`. It selects the three topic files, `Asia/Shanghai`, `07:30`, local keyword ranking and available-source recovery.

- `config/survival_continual.json`
- `config/gan_continual.json`
- `config/peft_agentic.json`

Topic files define search queries, keyword lists, venues, source adapters and retrieval limits. Customize them before starting a new topic. Use a separate output directory for changed research scope; existing state protects paper/report deduplication.

## Schedule on macOS

```bash
python3 scripts/install_schedule.py
```

This installs a user LaunchAgent that runs the combined digest at 07:30, at login and every five minutes for recovery checks. The application enforces the configured time zone; the calendar trigger uses machine-local time and periodic checks handle differences. `.env` is loaded on every invocation, so changing credentials does not require reinstalling the scheduler.

The laptop must be awake, logged in and connected to deliver mail. Missed delivery is retried after availability returns. The job does not power on or wake the machine.

```bash
# Inspect service and logs
launchctl print "gui/$(id -u)/com.literature-scout.daily"
tail -n 30 runs/daily.log runs/daily-error.log

# Stop the scheduled service
launchctl bootout "gui/$(id -u)/com.literature-scout.daily"
```

To generate a scheduler file without activating it:

```bash
bash scripts/scout.sh schedule
```

Moving the repository requires reinstalling the scheduler. Do not remove the active virtual environment or delivery history during cleanup.

## Schedule on Linux

Create `runs/` and add the following with `crontab -e`, using your actual repository path:

```cron
*/5 * * * * /bin/bash /path/to/PaperBeacon/scripts/daily_watch.sh >> /path/to/PaperBeacon/runs/daily.log 2>&1
@reboot /bin/bash /path/to/PaperBeacon/scripts/daily_watch.sh >> /path/to/PaperBeacon/runs/daily.log 2>&1
```

The application sends only when due and unsent, rather than on every check. Use one scheduler per laptop.

## Local files and recovery

Reports and state live under `runs/daily-three-topics/` and are excluded from Git:

```text
<topic>/baseline.json                    Initial ranked baseline
<topic>/baseline.txt                     Readable baseline
<topic>/candidates-START-END.json         Retrieved records before ranking
<topic>/candidates-START-END.txt          Readable candidates
<topic>/coverage-START-END.json           Retrieval diagnostics
collected/YYYY-MM-DD/<topic>-daily-DATE-*      Per-topic shortlists and reports
collected/YYYY-MM-DD/paperbeacon-daily-*  Combined papers, report and email
provider-recovery/                      Shared source health and query cache
digest-state.json                       Durable outbox and delivery history
```

Successful exact-query results are cached for six hours. Authentication failures stop repeated credential attempts until the key changes. OpenAlex's public search can fall back to documented anonymous access. Rate limits and service errors use persistent exponential cooldowns, beginning at 15 minutes, honoring longer `Retry-After` values and adding jitter. DBLP JSON parsing failures receive one XML-format fallback. See [OpenAlex authentication](https://help.openalex.org/api/authentication/), [Semantic Scholar API guidance](https://www.semanticscholar.org/product/api/tutorial) and [DBLP search formats](https://dblp.org/faq/How%2Bto%2Buse%2Bthe%2Bdblp%2Bsearch%2BAPI.html).

Available-source mode can prepare a report when some providers fail. Detailed coverage remains in local reports and metadata; operational logs are not included in the email. If all evidence is unavailable, collection is deferred. A partial baseline remains provisional and is not automatically rebuilt after provider recovery.

An email is saved before sending. After successful SMTP submission, delivery history advances. “Sent” means accepted by the SMTP server, not confirmed inbox placement. A crash immediately after acceptance but before local state is saved can still produce a duplicate; retries reuse the Message-ID. Back up the output directory separately to preserve duplicate protection. Missed days are not fully reconstructed after long outages: new discovery uses the current seven-day window.

## Email existing local records

```bash
bash scripts/scout.sh send-local --papers /path/to/papers.csv --preview
bash scripts/scout.sh send-local --papers /path/to/papers.csv \
  --title 'Spiking Transformers & Complementary Attention'
```

CSV and JSON inputs are supported, including multiple files after `--papers`. This sends up to five unreported records in file order, without retrieval or GPT. Saved records are labeled as such rather than as a new daily discovery report. Local-file delivery history is separate from scheduled digest history.

## Optional research intelligence

The optional `research` workflow analyzes mathematical foundations, evidence, gaps and experimental proposals. It requires an OpenAI API key and can incur API charges; it is separate from daily local ranking.

```bash
bash scripts/scout.sh research all
bash scripts/scout.sh research survival
bash scripts/scout.sh research gan
bash scripts/scout.sh research agents
```

It writes plain text and structured JSON research reports plus an Agentic Scientist handoff marked `awaiting_human_approval`. It never starts experiments. Source quotes are checked for traceability, not logical correctness or global novelty. See [architecture and extension notes](docs/ARCHITECTURE.md).

Legacy commands remain available:

```bash
.venv/bin/python -m literature_scout scan --config config/medqkformer.json --out runs/manual
.venv/bin/python -m literature_scout scan --config config/medqkformer.json \
  --offline-fixture examples/synthetic_fixture.json --out runs/demo
```

Offline fixtures are synthetic and must not be cited as real publications. Other research configurations and the context-export helper in `scripts/` remain available for compatibility.

## Prepare for GitHub

`.gitignore` excludes credentials, virtual environments, editor settings, reports, caches and logs. Keep `.env.example` as the public configuration template. Review `git status` before committing; do not force-add ignored files.

Initialize Git and connect your chosen GitHub repository when ready. Your Git commit email and GitHub account authentication are separate settings. This project does not configure either automatically.

MIT License. See [LICENSE](LICENSE).

## Historical recommendations on quiet days

When the combined recent-paper selection is empty, `historical_fallback: true` in `config/daily_digest.json` enables a second pass through each topic's saved baseline and candidate files. PaperBeacon ranks relevant older papers locally and recommends up to five that have never been reported. It does not fill a partially populated recent digest with old papers.

Historical recommendations are labeled **Historical picks** in the email, keep their original publication dates, and share normal delivery tracking and retry protection. After successful sending they are excluded from subsequent recommendations across all topics. Failed sends do not mark them delivered. When live retrieval fails but a matching local library exists, the digest can still recommend historical papers; it does not claim that no new papers exist.

This is an abstract-level revisit of existing records, not automatic full-text reading or AI-generated scientific analysis. The source library is restricted to the matching topic state and excludes future/undated records whose age cannot be established. No extra OpenAI calls are made in keyword mode. Set `historical_fallback` to `false` to disable it.

## Daily reporting and file naming

PaperBeacon delivers **one report every day at 07:30 Asia/Shanghai**, not once a week. The rolling seven-day publication window is a discovery lookback to accommodate indexing delays; already delivered papers are excluded. If the current lookback yields no eligible recommendations, the daily report can revisit unreported historical papers.

The scheduler uses `scripts/daily_watch.sh`. `scripts/weekly_watch.sh` remains only as a legacy single-topic compatibility entry point and is not scheduled by the combined workflow. Do not schedule both.

New output names explicitly identify daily reports:

```text
collected/YYYY-MM-DD/<topic>-daily-YYYY-MM-DD-papers.json
collected/YYYY-MM-DD/<topic>-daily-YYYY-MM-DD-report.txt
collected/YYYY-MM-DD/paperbeacon-daily-YYYY-MM-DD-papers.json
collected/YYYY-MM-DD/paperbeacon-daily-YYYY-MM-DD-report.txt
collected/YYYY-MM-DD/paperbeacon-daily-YYYY-MM-DD-email.json
paperbeacon-daily-YYYY-MM-DD.txt
```

Baseline files and `candidates-START-END` files retain date-window names because they describe retrieved literature rather than delivery frequency. Existing archives and `digest-state.json` are preserved; changing filenames does not reset successful delivery history or resend a report.
