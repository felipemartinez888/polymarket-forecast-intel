# Operations, deployment & troubleshooting

## Architecture

* **No server, no database.** GitHub Actions runs the Python pipeline on a schedule, writes JSON/JSONL files, and force-pushes them to the `data` branch as a **single commit** (history never grows). The static React build reads those JSON files. If a run fails, nothing is committed and the site keeps serving the last valid data.
* Each run also uploads the data directory as a workflow artifact (kept 14 days) for recovery.

```
data/ (branch `data`)
  registry.json              events + markets metadata, classification, resolution status history
  history/<market_id>.json   CLOB probability history of the tracked outcome
  snapshots/YYYY-MM.jsonl    6-hourly Gamma price snapshots (append-only, 1 per market per hour)
  runs.json                  last 300 runs: status, counts, API errors, incomplete windows
  derived/                   analytics for the dashboard + exports/ (CSV, JSON)
```

## Schedules (edit `.github/workflows/pipeline.yml`)

| Job | Default | Notes |
|---|---|---|
| discover | `17 */6 * * *` | new markets, live snapshots, incremental history |
| resolve | `47 7 * * *` daily | re-checks closed/past-deadline events, fetches final histories, freezes finished events |
| analyze | after every run | pure computation, no network |
| backfill | manual | `Run workflow → backfill` (optionally limit N markets per run) |
| deploy | after every run, and on frontend changes | |

GitHub may delay scheduled runs at busy times, and **disables schedules in public repos after 60 days without repository activity** — the bot's commits to the `data` branch normally keep it active, but if collection stops, re-enable the workflow in the Actions tab.

Tunables live in `config/settings.json`: search queries, tags, history fidelity (minutes), horizons and staleness limits, shift thresholds, bootstrap samples, HTTP retries/backoff/rate limit.

## Deployment

### Cloudflare Pages (default)
1. Cloudflare dashboard → My Profile → API Tokens → *Create token* → custom: **Account · Cloudflare Pages · Edit**.
2. GitHub repo → Settings → Secrets and variables → Actions:
   * secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` (Cloudflare dashboard sidebar)
   * variable `CF_PAGES_PROJECT` (optional, default `forecast-intel`)
3. Run *Collect data & deploy* (`all`). The deploy job creates the Pages project if needed and publishes `https://<project>.pages.dev`.

Uses Wrangler *direct upload* (no Cloudflare build minutes). ~5 deployments/day ≈ 150/month, below the free plan's 500 builds/month even if counted. Free-plan limits: 20,000 files per deployment, 25 MiB per file — the size report in each run summary shows where you stand (each tracked market adds one history file).

### GitHub Pages (alternative, no Cloudflare account)
Set variable `DEPLOY_TARGET=github-pages`; Settings → Pages → Source: *GitHub Actions*. Free for public repos.

### Access control
The site has no login. Cloudflare Zero Trust Access (free up to 50 users) can put it behind email one-time-pin auth without code changes. A `noindex` header is set by default.

## Maintenance tasks

* **After each FOMC meeting**: fill `decision_bps`, `target_range_after`, `statement_url` for that meeting in `config/fomc_meetings.json` (source: federalreserve.gov). Add next year's meetings when the Fed publishes the calendar. Until then, those markets remain quality B and unverified.
* **New market families** (e.g. a new bill name): add a search query in `settings.json` and, if needed, a rule in `classification_rules.json`; bump the rules `version`.
* **Misclassified or problematic market**: add an entry to `config/overrides.json` (`exclude`, `category`, `relevance`, `external_source`, `reference_time`).
* **Changing a formula**: bump `calc_version`; all derived files and exports are recomputed on the next run.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Site says “No collected data is deployed yet” | Run *Collect data & deploy* once; check that the `data` branch exists. |
| Run marked `partial` | Some API calls failed after 5 retries. Valid data was kept; incomplete windows are listed in `runs.json` and the Data page. They are retried next run. |
| Run `failed`, nothing committed | See the job log (structured JSON lines). Previous data is untouched. |
| Deploy job: “CLOUDFLARE_API_TOKEN not set — skipping” | Add the secrets (above). |
| `wrangler … Authentication error` | Token lacks *Cloudflare Pages: Edit* or account id is wrong. |
| A market has no history / every horizon missing | CLOB returned no data for that token (common for very old or very illiquid markets). Shown as missing by design. |
| Fed meeting shows `unmatched_meeting` | Event title has no month name and its end date is > 7 days from any meeting in `fomc_meetings.json` — add the meeting, or set an override. |
| Polymarket schema change | Parsing errors are recorded per market (`parse_warnings` flag); the run continues. Update `pipeline/parse.py`. |
| Rate limiting (HTTP 429) | Increase `http.min_interval_seconds` in settings. |
| Scheduled runs stopped | Public repo inactive 60 days → re-enable workflow in Actions. |

## Cost

| Item | Usage | Cost |
|---|---|---|
| GitHub Actions | ~5 runs/day × 2–6 min ≈ 300–900 min/month | $0 (public repo: unlimited; private: 2,000 free min/month) |
| GitHub storage | data branch is one commit; history files a few MB | $0 |
| Workflow artifacts | 14-day retention of a few MB | $0 (public); within 500 MB free (private) |
| Cloudflare Pages | static hosting, direct uploads | $0 |
| Polymarket APIs, federalreserve.gov | public, no key | $0 |
| **Total** | | **$0/month** |

## Security

Read-only GET requests only; no API keys, wallet keys or Polymarket credentials anywhere. The only secrets are the Cloudflare deploy token and account id, stored as GitHub secrets. All external payloads are validated (types, ranges, lengths) before storage.
