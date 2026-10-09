# Forecast Intel — how good are Polymarket's probabilities?

A $0/month research dashboard that collects Polymarket markets on **Fed decisions, crypto regulation (CLARITY Act, stablecoins, SEC/CFTC), macro data and crypto ETFs**, stores their full probability histories, and scores them against real outcomes with proper probabilistic metrics (Brier, multi-outcome Brier, calibration, skill vs baselines, lead-time analysis) — without look-ahead bias or double counting.

It is a read-only research tool. It never trades, never asks for wallet keys or Polymarket credentials, and nothing it shows is a trading signal.

```
             ┌──────────── GitHub Actions (free) ────────────┐
Polymarket   │ every 6h  discover  ─┐                         │
Gamma + CLOB ├─►daily    resolve   ─┼─► analyze ─► data branch├─► build ─► Cloudflare Pages
(public API) │ manual    backfill  ─┘   (static JSON, 1 commit)│          (or GitHub Pages)
             └───────────────────────────────────────────────┘
federalreserve.gov (transcribed into config/fomc_meetings.json) ─► external verification
```

| Piece | Where |
|---|---|
| Data pipeline (Python 3.11+, **stdlib only**) | `pipeline/` |
| Configuration: schedule-independent settings, classification rules, FOMC decisions, overrides, official links | `config/` |
| Tests (pytest, synthetic fixtures clearly marked) | `tests/` |
| Dashboard (React + TypeScript + Vite + Tailwind + Recharts, static) | `frontend/` |
| Workflows: CI, scheduled collection + deploy | `.github/workflows/` |
| Methodology, operations, data dictionary | `docs/` |

## Quick start (deploy your own copy)

1. **Create a GitHub repository** and push this code to `main`.
   *Public* repos get unlimited free Actions minutes; private repos get 2,000 min/month (this project uses roughly 300–600 — see [cost](docs/OPERATIONS.md#cost)).
2. **Cloudflare Pages** (recommended): create an API token with *Account → Cloudflare Pages → Edit*, then in the GitHub repo settings add
   - secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`
   - (optional) variable `CF_PAGES_PROJECT` (default `forecast-intel`)
   The site will be at `https://<project>.pages.dev`.
   *Alternative:* set repository variable `DEPLOY_TARGET=github-pages` and enable Pages → Source: GitHub Actions.
3. **Run the first collection:** Actions → *Collect data & deploy* → Run workflow → `all`. Then run it once more with `backfill` to fetch full price histories for every historical market found.
4. From then on everything is automatic (6-hourly collection, daily resolution checks, redeploy after each run).

Local development:
```bash
pip install -r requirements-dev.txt && python -m pytest -q        # tests
python -m pipeline.cli all                                          # collect into ./data (needs internet)
cd frontend && npm install && npm run sync-data && npm run dev      # dashboard on http://localhost:5173
```

## What the dashboard answers

| Question | Page |
|---|---|
| How accurate / well-calibrated has Polymarket been? | Historical accuracy (calibration with Wilson CIs, Brier by category and horizon, skill scores with bootstrap CIs) |
| Does accuracy improve as the event approaches? | Brier by horizon: 30d, 14d, 7d, 3d, 24h, final pre-event observation |
| Which categories are more predictable? | By-category tables (binary and multi-outcome kept separate; scale-free skill score to compare) |
| Is it getting better or worse? | Quarterly trend of skill score |
| What moved recently? | Probability shifts (pp vs relative change, configurable thresholds) |
| What's next for the Fed / CLARITY Act? | Fed monitor, Crypto regulation monitor |

## Honest limitations (read these)

- **Sample sizes are small.** There are only ~8 FOMC meetings a year and a handful of crypto-law milestones. Confidence intervals are shown; most category-level conclusions will be inconclusive for a long time.
- **Data starts where Polymarket's public history starts.** Markets the search does not surface, or whose CLOB history is empty, are recorded as missing — never filled in.
- **External verification is automatic only for FOMC decisions.** Other outcomes rely on Polymarket's UMA resolution (quality B) or settlement prices (quality C). Add an `external_source` override to attach a primary source.
- **Reference times for early-resolving “by date” markets are estimated** from the price path (flagged on the market page). See [methodology](docs/METHODOLOGY.md#reference-time).
- **No competing-forecaster baseline** (e.g. CME FedWatch): no free, reproducible archive is used, so the tool does not claim Polymarket beats other forecasters — only how it compares with uninformed and base-rate forecasts.
- **Event probability ≠ crypto price impact.** Relevance tags (high/medium/low) are transparent rules about what crypto investors may want to watch, not predictions of market reactions.

Docs: [Methodology](docs/METHODOLOGY.md) · [Operations, deployment, troubleshooting, cost](docs/OPERATIONS.md) · [Data dictionary](docs/DATA_DICTIONARY.md)
