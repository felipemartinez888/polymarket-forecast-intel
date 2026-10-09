# Methodology

Calculation version: `config/settings.json → calc_version` (currently 1.0.0). Every export carries it.

## 1. Sources

| Data | Endpoint (verified against Polymarket's published API reference) |
|---|---|
| Discovery | `GET gamma-api.polymarket.com/public-search?q=…&keep_closed_markets=1` and `GET /events?tag_slug=…&closed=…&offset=…` |
| Event + market metadata, resolution state | `GET gamma-api.polymarket.com/events/{id}` (fields `outcomes`, `outcomePrices`, `clobTokenIds`, `umaResolutionStatuses` are JSON-encoded strings) |
| Probability history | `GET clob.polymarket.com/prices-history?market=<token>&interval=max&fidelity=60` (falls back to 14-day `startTs`/`endTs` windows when `interval=max` returns nothing) |
| Live snapshots | Gamma `outcomePrices` of the tracked outcome at each 6-hourly run, de-duplicated per market per hour |
| FOMC decisions | federalreserve.gov calendar + target-range history, transcribed into `config/fomc_meetings.json` with statement URLs |

The tracked outcome is “Yes” for Yes/No markets, otherwise outcome index 0 (its label is recorded).

## 2. Resolution states

| State | Rule | Scored? |
|---|---|---|
| unresolved | market not closed | no |
| proposed / disputed | UMA status says so | no |
| final | closed and settlement vector is one-hot (±0.01) | **yes** |
| invalid | closed and settled at equal split (50/50) | no |
| closed_unverified | closed, but settlement prices missing/malformed or not one-hot | no |

Outcomes are never inferred from the end date. `final` markets get a quality grade: **A** – externally verified against an official source (FOMC); **B** – UMA reported `resolved`; **C** – one-hot settlement prices but no UMA status. A Fed market whose Polymarket outcome conflicts with the official decision is excluded and flagged.

## 3. Reference time

Forecasts are scored relative to the moment the outcome became knowable:

1. **Manual override** (`config/overrides.json → reference_time`), if set.
2. **Scheduled announcement**: FOMC decision markets matched to an official meeting use 14:00 America/New_York on the statement day.
3. **Settlement onset** (deadline-style markets that resolved YES): the earliest time after which every observed price stays within 5 pp of 1. This prevents treating post-event prices (e.g. after a bill is signed but before the market's deadline) as forecasts. Flagged `reference_time_estimated_from_price_path`.
4. Otherwise the **market end date** (or closed time if earlier).

For mutually exclusive (negRisk) events every outcome uses the **earliest** reference time in the event — once any outcome is known, every sibling price is post-event.

*Known limitation:* a deadline market that became impossible early (resolves NO before its deadline) is still referenced to its end date; such forecasts near the end may already reflect the known outcome, slightly flattering the final-horizon score. Use the `reference_time` override where this matters.

## 4. Point-in-time forecasts (look-ahead prevention)

For horizon *h* ∈ {30d, 14d, 7d, 3d, 24h, final}: forecast = last observed price with `t ≤ reference − h` (minus 60 s for `final`) and `t < reference`. It is **missing** if no observation exists yet (`market_not_yet_trading`), if the observation is older than the staleness limit (2 d for 30/14 d, 1 d for 7 d, 12 h for 3 d, 6 h for 24 h, 24 h for final), or if there is no history. Missing values are never filled with the closing price or any other value. An assertion enforces `t < reference` in code and tests.

## 5. Scoring units and double counting

* **Duplicates**: markets with the same normalized question and end date (UTC day) are duplicates; the highest-volume one is canonical, the rest are excluded.
* **Multiclass unit**: a negRisk event whose tracked markets are the event's full outcome set, with exactly one YES. The probability vector at each horizon is normalized to sum to 1 (the raw sum is stored) and scored with the multiclass Brier score. If any outcome lacks a forecast, the unit is missing at that horizon.
* **Binary-set unit**: any other event. Each final market gets a binary Brier score; the event's score is the **mean** over its markets, so each event weighs 1 regardless of how many related markets it lists.
* **FOMC**: all units mapped to the same official meeting collapse to one primary unit (multiclass preferred, then highest volume). Others stay visible but are marked `correlated_with` and excluded from aggregates.
* One forecast per market per horizon — repeated snapshots never enter the scoring sample.
* Crypto price-direction markets are collected but never enter accuracy statistics.

## 6. Metrics

| Metric | Formula | Scale / reference |
|---|---|---|
| Binary Brier | (p − o)² | 0 best, 1 worst; always-50 % forecast = 0.25 |
| Multiclass Brier | Σₖ (pₖ − oₖ)² over the normalized vector | 0 best, 2 worst; uniform 1/K forecast = 1 − 1/K. For K = 2 it equals 2 × binary Brier, so **the two scales are never averaged together** |
| Brier skill score (BSS) | 1 − Σ BS / Σ BS_ref over the same units | scale-free; > 0 beats the reference. Pooled BSS is used to compare binary and multiclass categories |
| Log loss | −log(clip(p, 1 %, 99 %)) for the realized outcome | |
| MAE | mean │p − o│ (binary) | |
| Directional accuracy | share of correct calls when │p − 0.5│ ≥ 5 pp; coverage reported | classification, **not** probabilistic accuracy |
| Calibration | 10 equal-width bins (last closed at 100 %), n, mean p, observed frequency, gap, Wilson 95 % CI, ECE | bins with n < 10 flagged low-sample |
| Volatility | std-dev of day-to-day probability changes over the 30 days before reference | probability units |
| Time-weighted mean p | step-interpolated average over the 30 days before reference | |
| CIs on means and skill | event-level (paired) bootstrap, 2,000 resamples, fixed seed | deterministic |

There is deliberately no single “accuracy %”.

### Baselines

* **Uniform**: 0.5 for binary markets, 1/K for multiclass units.
* **Expanding base rate** (binary): Laplace-smoothed (k + 1)/(n + 2) YES rate among same-subcategory markets whose reference time precedes the forecast time `reference − h`. It uses no future information.
* Not included: external forecasters (CME FedWatch, surveys) — no free reproducible archive.

## 7. Independence caveat

Units are treated as independent for confidence intervals. Consecutive FOMC meetings, CPI prints and Fed decisions share drivers, so true uncertainty is wider than shown. Calibration bins include every outcome of multi-outcome events, which are mechanically correlated.

## 8. Classification & relevance

`config/classification_rules.json` holds ordered regex rules over `event title || question || outcome label`. The first match assigns category, subcategory and crypto relevance (high/medium/low) and records the rule id on every market. Crypto price-direction rules are evaluated first so those markets never leak into regulation or macro categories. `config/overrides.json` can change category/relevance, exclude a market, attach an external source, or set a reference time; overrides are recorded on the market.

Relevance is a statement about attention, not about price impact. A “high” relevance Fed market means Fed outcomes plausibly matter to crypto investors; it says nothing about whether Bitcoin will rise or fall, or whether the outcome is priced in. No trading performance is claimed or implied.

## 9. Probability shifts

For each active market: current value (latest Gamma snapshot or CLOB point), value 24 h ago (nearest observation at or before, within 6 h) and 7 d ago (within 24 h). Reported as **percentage-point** change and **relative** change ((now − then)/then, omitted when the base is < 1 %). Flags at ≥ 10 pp/24 h or ≥ 15 pp/7 d by default (configurable in `settings.json` and live in the UI).
