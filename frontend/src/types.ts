// Shapes of the JSON produced by pipeline/analyze.py (see docs/DATA_DICTIONARY.md).

export type HorizonKey = "30d" | "14d" | "7d" | "3d" | "24h" | "final";
export const HORIZONS: HorizonKey[] = ["30d", "14d", "7d", "3d", "24h", "final"];

export interface Meta {
  generated_at: string;
  calc_version: string;
  rules_version?: string;
  fomc_transcribed_at?: string;
}

export interface Forecast {
  status: "ok" | "missing" | "future";
  p?: number;
  obs_ts?: number;
  target_ts?: number;
  staleness_s?: number;
  reason?: string;
}

export interface Verification {
  status: string;
  source: string | null;
  expected_yes: boolean | null;
  detail: string | null;
}

export interface MarketRow {
  market_id: string;
  event_id: string;
  question: string;
  group_item_title: string | null;
  event_title: string;
  category: string | null;
  subcategory: string | null;
  relevance: string | null;
  rule_id: string | null;
  override: Record<string, unknown> | null;
  excluded: boolean;
  scored_category: boolean;
  url: string | null;
  outcomes: string[];
  tracked_outcome: string | null;
  status: string;
  resolution_basis: string | null;
  uma_status: string | null;
  winner: string | null;
  outcome_value: number | null;
  status_history: { status: string; observed_at: number; uma: string | null }[];
  current_p: number | null;
  final_settlement_prices: number[] | null;
  end_ts: number | null;
  closed_ts: number | null;
  start_ts: number | null;
  reference_ts: number | null;
  reference_method: string;
  volume: number | null;
  liquidity: number | null;
  volume_24h: number | null;
  forecasts: Partial<Record<HorizonKey, Forecast>>;
  brier: Partial<Record<HorizonKey, number>>;
  volatility_30d: number | null;
  time_weighted_p_30d: number | null;
  resolution_source: string | null;
  description: string | null;
  external_verification: Verification | null;
  external_source: string | null;
  duplicate_of: string | null;
  correlated_with: string | null;
  quality: "A" | "B" | "C" | null;
  flags: string[];
  completeness: number;
  n_history_points: number;
  first_obs_ts: number | null;
  last_obs_ts: number | null;
  retrieved_at: number | null;
  fomc_meeting_id: string | null;
  clarity_milestone: string | null;
}

export type Brief = Pick<MarketRow,
  "market_id" | "event_id" | "question" | "group_item_title" | "event_title" | "subcategory" | "status" | "current_p" |
  "winner" | "end_ts" | "url" | "brier" | "relevance" | "clarity_milestone" | "external_source" | "quality" | "flags" | "volume">;

export interface AggEntry {
  n_events: number;
  mean_brier: number | null;
  ci95: [number, number] | null;
  bss_vs_uniform: number | null;
  bss_vs_uniform_ci95: [number, number] | null;
  bss_vs_base_rate?: number | null;
  bss_vs_base_rate_ci95?: [number, number] | null;
  mean_brier_base_rate?: number | null;
}

export interface Agg {
  binary_set: AggEntry;
  multiclass: AggEntry;
  pooled_bss_vs_uniform: number | null;
  n_events: number;
}

export interface CalBin {
  bin: string; lo: number; hi: number; n: number; events: number;
  mean_forecast: number | null; observed_freq: number | null; gap: number | null;
  ci_low: number | null; ci_high: number | null; low_sample: boolean;
}

export interface MarketLevel {
  n: number; mean_brier?: number; brier_ci95?: [number, number] | null; log_loss?: number; mae?: number;
  directional_accuracy?: number | null; directional_coverage?: number; base_rate_yes?: number; bss_vs_0_5?: number | null;
}

export interface Performance extends Meta {
  horizons: HorizonKey[];
  by_horizon: Record<HorizonKey, Agg>;
  by_category: Record<string, Record<HorizonKey, Agg>>;
  by_subcategory: { category: string; subcategory: string; by_horizon: Partial<Record<HorizonKey, Agg>> }[];
  market_level: Record<HorizonKey, MarketLevel>;
  calibration: Record<HorizonKey, { n: number; bins: CalBin[]; ece: number | null }>;
  trend: { horizon: HorizonKey; quarter: string; n_events: number; pooled_bss_vs_uniform: number | null;
    mean_brier_binary: number | null; mean_brier_multiclass: number | null; low_sample: boolean }[];
  coverage: Record<HorizonKey, { units_final: number; units_with_forecast: number; missing_reasons: Record<string, number> }>;
  unit_status_counts: Record<string, number>;
  exclusions: Record<string, number>;
  quality_counts: Record<string, number>;
  n_primary_scored_events: number;
  independence_caveat: string;
}

export interface ShiftChange { past_p: number; past_ts: number; pp_change: number; relative_change_pct: number | null }
export interface Shift {
  market_id: string; event_id: string; question: string; label: string | null; event_title: string;
  category: string; subcategory: string; relevance: string; current_p: number; current_ts: number;
  d24h: ShiftChange | null; d7d: ShiftChange | null; flag_24h: boolean; flag_7d: boolean;
  volume: number | null; liquidity: number | null; volume_24h: number | null; end_ts: number | null; url: string | null;
}
export interface Shifts extends Meta { thresholds: { pp_24h: number; pp_7d: number }; note: string; markets: Shift[] }

export interface Summary extends Meta {
  counts: { markets: number; active: number; units: number; scored_primary_events: number };
  upcoming: Brief[]; awaiting_resolution: Brief[]; recently_resolved: Brief[];
  movers_24h: Shift[]; movers_7d: Shift[];
  headline: Record<HorizonKey, Agg>;
  by_category_final: Record<string, Agg | undefined>;
  freshness: { last_success: Record<string, string>; latest_observation_ts: number | null };
}

export interface FedOutcome {
  market_id: string; label: string; probabilities: Partial<Record<HorizonKey, number | null>>;
  missing: Partial<Record<HorizonKey, string>>; current_p: number | null; status: string;
  outcome_value: number | null; verification: Verification | null; shift: Shift | null;
}
export interface FedEvent {
  event_id: string; title: string; url: string | null; neg_risk: boolean; volume: number | null;
  unit: { unit_id: string; type: string; status: string; primary: boolean; correlated_with: string | null;
    scores: Partial<Record<HorizonKey, number>>; baseline_uniform: Partial<Record<HorizonKey, number>>; exclusion_reason: string | null } | null;
  outcomes: FedOutcome[];
}
export interface FedMeeting {
  id: string; announcement_date: string; decision_bps: number | null; target_range_after: string | null;
  statement_url: string | null; announcement_ts: number; is_past: boolean; events: FedEvent[];
}
export interface Fed extends Meta {
  official_sources: { label: string; url: string }[];
  meetings: FedMeeting[]; upcoming_meeting_id: string | null;
  brier_by_lead_time: Record<HorizonKey, { n_events: number; mean_brier: number | null; bss_vs_uniform: number | null; types: string[] }>;
  other_fed_markets: Brief[];
}

export interface Regulation extends Meta {
  groups: { category: string; subcategory: string; markets: Brief[] }[];
  clarity_milestones: Record<string, Brief[]>;
  milestone_order: string[];
  official_sources: Record<string, { label: string; url: string }[]>;
  note: string;
}

export interface RunRec {
  command: string; started_at: string; finished_at: string; status: string; duration_s: number;
  result?: Record<string, unknown>; n_errors?: number; incomplete?: { market_id: string; reason: string }[]; error?: string;
}
export interface Status extends Meta {
  last_success: Record<string, string>; recent_runs: RunRec[]; latest_observation_ts: number | null;
  n_markets: number; n_events: number; storage: { bytes: number; files: number };
  markets_without_history: number; categories: Record<string, number>;
}

export interface History { market_id: string; token_id: string; outcome: string; points: [number, number][]; retrieved_at: number; fidelity_minutes: number }
