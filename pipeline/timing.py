"""Reference-time alignment and point-in-time forecast extraction (look-ahead bias prevention).

Every forecast used for scoring is the last observed price at or before
    reference_time - horizon - (buffer if horizon == 0),
strictly before the reference time, and no older than the horizon's staleness tolerance.
"""
from __future__ import annotations

from bisect import bisect_right


def settlement_onset(points: list[list], final_outcome: int, band: float, cap_ts: int | None) -> int | None:
    """Earliest t after which every observed price stays within `band` of the final outcome (0/1).

    Used ONLY to estimate when an early-resolving event became known, so that post-event
    prices are never treated as forecasts. Returns None if the path never settles.
    """
    pts = [p for p in points if cap_ts is None or p[0] <= cap_ts]
    if not pts:
        return None
    onset = None
    for t, p in reversed(pts):
        if abs(p - final_outcome) <= band:
            onset = t
        else:
            break
    return onset


def reference_time(market: dict, event_kind: str, scheduled_ts: int | None, points: list[list],
                   band: float, override_ts: int | None = None) -> tuple[int | None, str]:
    """Return (reference_ts, method).

    - override:              manual reference_time from overrides.json
    - scheduled_announcement: official scheduled release (e.g. FOMC statement 14:00 ET)
    - settlement_onset:      deadline-style market resolved YES, price path settled before the deadline
    - end_date:              market end date (event did not happen before the deadline)
    - closed_time:           fallback when no end date exists
    """
    if override_ts:
        return override_ts, "override"
    if scheduled_ts:
        return scheduled_ts, "scheduled_announcement"
    end = market.get("end_ts")
    closed = market.get("closed_ts")
    cap = min(x for x in (end, closed) if x) if (end or closed) else None
    res = market.get("resolution", {})
    yes_won = res.get("status") == "final" and res.get("winner_index") == market.get("track_index")
    if event_kind == "deadline" and yes_won and points:
        onset = settlement_onset(points, 1, band, cap)
        if onset is not None and (cap is None or onset < cap):
            return onset, "settlement_onset"
    if end:
        return (min(end, closed) if closed else end), "end_date"
    if closed:
        return closed, "closed_time"
    return None, "unknown"


def forecast_at(points: list[list], ref_ts: int, horizon_s: int, max_stale_s: int,
                buffer_s: int = 60) -> dict:
    """Point-in-time forecast. `points` must be sorted [[t, p], ...]."""
    target = ref_ts - horizon_s - (buffer_s if horizon_s == 0 else 0)
    target = min(target, ref_ts - 1)
    if not points:
        return {"status": "missing", "reason": "no_price_history", "target_ts": target}
    ts = [p[0] for p in points]
    i = bisect_right(ts, target) - 1
    if i < 0:
        return {"status": "missing", "reason": "market_not_yet_trading", "target_ts": target}
    t, p = points[i]
    if target - t > max_stale_s:
        return {"status": "missing", "reason": "stale_observation", "target_ts": target, "obs_ts": t}
    assert t < ref_ts, "look-ahead violation"
    return {"status": "ok", "p": p, "obs_ts": t, "target_ts": target, "staleness_s": target - t}


def value_at_or_before(points: list[list], ts: int, tolerance_s: int) -> tuple[int, float] | None:
    if not points:
        return None
    idx = bisect_right([p[0] for p in points], ts) - 1
    if idx < 0 or ts - points[idx][0] > tolerance_s:
        return None
    return points[idx][0], points[idx][1]
