# Data dictionary

All timestamps are Unix seconds UTC unless suffixed `_utc` (ISO-8601) in CSV exports.

## `derived/markets.json → markets[]` (one row per tracked market)

| Field | Meaning |
|---|---|
| market_id, event_id | Polymarket ids |
| question, group_item_title, event_title | text as returned by Gamma; group_item_title is the outcome label inside multi-outcome events |
| category, subcategory, relevance, rule_id, override | classification and its audit trail |
| url | Polymarket event page |
| outcomes, tracked_outcome | outcome labels; the outcome whose probability is stored and scored |
| status | unresolved · proposed · disputed · final · invalid · closed_unverified |
| resolution_basis, uma_status, status_history | why the status was assigned; every status change with the time it was observed |
| winner, outcome_value | winning label; 1/0 for the tracked outcome (final only) |
| current_p | latest Gamma price (open markets) |
| final_settlement_prices | settlement vector (closed markets) |
| start_ts, end_ts, closed_ts | market dates |
| reference_ts, reference_method | moment the outcome is treated as known; see methodology §3 |
| forecasts[h] | `{status, p, obs_ts, target_ts, staleness_s}` or `{status: missing, reason}` / `{status: future}` |
| brier[h] | binary Brier score of the tracked outcome at horizon h |
| volatility_30d, time_weighted_p_30d | path statistics before reference |
| external_verification | `{status: verified|conflict|unmatched_meeting|official_decision_pending|unmapped_outcome_label|…, source, expected_yes, detail}` |
| external_source, resolution_source | official verification link; the market's own stated source |
| duplicate_of, correlated_with | de-duplication / correlation bookkeeping |
| quality | A (externally verified) · B (UMA resolved) · C (settlement prices only) |
| flags | data-quality warnings |
| completeness | share of horizons with a valid forecast |
| n_history_points, first_obs_ts, last_obs_ts, retrieved_at | provenance |

## `derived/units.json → units[]` (scoring units)

`unit_id`, `event_id`, `type` (multiclass | binary_set), `status` (final | pending | not_scoreable), `primary`, `correlated_with`, `exclusion_reason`, `market_ids`, `labels`, `reference_ts`, `quality`, `K`, `scores[h]`, `forecasts[h]` (multiclass: raw and normalized vectors, raw sum, observation times, log loss, whether the top outcome won), `baseline_uniform[h]`, `baseline_base_rate[h]`.

## Exports (`derived/exports/`)

* `market_forecasts.csv` — one row per market: ids, classification, resolution, reference time, p / observation time / Brier at each horizon, quality, flags, calc_version, retrieval time.
* `event_scores.csv` — one row per scoring unit with scores and both baselines per horizon.
* `accuracy_metrics.json` — every aggregate on the accuracy page plus the full settings used.

## Raw storage (branch `data`)

* `registry.json` — parsed Gamma metadata per event and market (as above plus raw prices, token ids, tags).
* `history/<market_id>.json` — `{market_id, token_id, outcome, source, fidelity_minutes, points: [[t, p], …], retrieved_at, first_ts, last_ts}`.
* `snapshots/YYYY-MM.jsonl` — `{t, market_id, event_id, outcome, p, bid, ask, last, vol24h, liq, src}`.
* `runs.json` — `{runs: [{command, started_at, finished_at, status, result, errors, incomplete, http_requests, calc_version}], last_success: {command: iso}}`.
