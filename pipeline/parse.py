"""Parsing and validation of Gamma API payloads into internal records.

Gamma encodes `outcomes`, `outcomePrices`, `clobTokenIds` and `umaResolutionStatuses`
as JSON-encoded *strings* (verified against the published OpenAPI spec). Every field is
validated; malformed records are kept with a `parse_errors` list rather than guessed at.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

ONE_HOT_TOL = 0.01


class ParseError(ValueError):
    pass


def _json_list(v, field: str, errors: list) -> list | None:
    if v is None or v == "":
        return None
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            out = json.loads(v)
        except json.JSONDecodeError:
            errors.append(f"{field}: invalid JSON string")
            return None
        if not isinstance(out, list):
            errors.append(f"{field}: not a list")
            return None
        return out
    errors.append(f"{field}: unexpected type {type(v).__name__}")
    return None


def parse_ts(v) -> int | None:
    """Parse an ISO-8601 timestamp (or epoch seconds) into integer epoch seconds UTC."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v if v < 1e11 else v / 1000)
    s = str(v).strip()
    # Gamma sometimes emits "2024-09-18 18:00:00+00" style values
    s = s.replace(" ", "T", 1) if re.match(r"^\d{4}-\d{2}-\d{2} \d", s) else s
    s = re.sub(r"Z$", "+00:00", s)
    s = re.sub(r"([+-]\d{2})$", r"\1:00", s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # drop NaN


def resolution_from_market(m: dict) -> dict:
    """Determine resolution state from Gamma market fields.

    States:
      unresolved  - market still open
      proposed    - UMA outcome proposed, challenge window open
      disputed    - UMA proposal disputed, awaiting DVM vote
      final       - closed with a one-hot settlement price vector
      invalid     - closed and settled 50/50 (Polymarket's 'unknown/invalid' resolution)
      closed_unverified - closed but settlement cannot be confirmed (canceled / pending / malformed)

    A winner is ONLY assigned for `final`. End dates are never used to infer outcomes.
    """
    errors: list[str] = []
    outcomes = _json_list(m.get("outcomes"), "outcomes", errors) or []
    prices_raw = _json_list(m.get("outcomePrices"), "outcomePrices", errors) or []
    prices = [_num(p) for p in prices_raw]
    uma = (m.get("umaResolutionStatus") or "").strip().lower() or None
    uma_hist = [str(s).lower() for s in (_json_list(m.get("umaResolutionStatuses"), "umaResolutionStatuses", errors) or [])]
    closed = bool(m.get("closed"))
    was_disputed = "disputed" in uma_hist or uma == "disputed"

    out = {
        "status": "unresolved",
        "winner_index": None,
        "winner_label": None,
        "uma_status": uma,
        "was_disputed": was_disputed,
        "basis": None,
        "errors": errors,
    }
    if not closed:
        if uma in ("proposed", "disputed"):
            out["status"] = uma
            out["basis"] = "uma_status"
        return out

    if uma in ("proposed", "disputed"):
        out["status"] = uma
        out["basis"] = "uma_status"
        return out

    valid = len(prices) == len(outcomes) and len(prices) >= 2 and all(p is not None for p in prices)
    if not valid:
        out["status"] = "closed_unverified"
        out["basis"] = "malformed_or_missing_settlement_prices"
        return out

    hi = [i for i, p in enumerate(prices) if p >= 1 - ONE_HOT_TOL]
    lo = [i for i, p in enumerate(prices) if p <= ONE_HOT_TOL]
    if len(hi) == 1 and len(lo) == len(prices) - 1:
        out["status"] = "final"
        out["winner_index"] = hi[0]
        out["winner_label"] = outcomes[hi[0]]
        out["basis"] = "uma_resolved" if uma == "resolved" else "settlement_prices_only"
        return out
    if all(abs(p - 1 / len(prices)) <= ONE_HOT_TOL for p in prices):
        out["status"] = "invalid"
        out["basis"] = "equal_split_settlement"
        return out
    out["status"] = "closed_unverified"
    out["basis"] = "closed_without_one_hot_settlement"
    return out


def parse_market(m: dict, event: dict | None = None) -> dict:
    if not isinstance(m, dict) or not m.get("id"):
        raise ParseError("market without id")
    errors: list[str] = []
    outcomes = _json_list(m.get("outcomes"), "outcomes", errors) or []
    prices = [_num(p) for p in (_json_list(m.get("outcomePrices"), "outcomePrices", errors) or [])]
    tokens = [str(t) for t in (_json_list(m.get("clobTokenIds"), "clobTokenIds", errors) or [])]
    if outcomes and tokens and len(outcomes) != len(tokens):
        errors.append("outcomes/clobTokenIds length mismatch")
    for p in prices:
        if p is not None and not (0.0 <= p <= 1.0):
            errors.append(f"price out of range: {p}")

    # The tracked outcome is "Yes" when present, otherwise outcome index 0 (label recorded).
    lower = [str(o).strip().lower() for o in outcomes]
    track_idx = lower.index("yes") if "yes" in lower else 0
    res = resolution_from_market(m)
    ev = event or {}
    ev_slug = ev.get("slug") or ((m.get("events") or [{}])[0] or {}).get("slug")
    tags = [t.get("label") for t in (m.get("tags") or ev.get("tags") or []) if isinstance(t, dict) and t.get("label")]

    return {
        "market_id": str(m["id"]),
        "event_id": str(ev.get("id") or ((m.get("events") or [{}])[0] or {}).get("id") or "") or None,
        "condition_id": m.get("conditionId"),
        "question": (m.get("question") or "").strip(),
        "group_item_title": (m.get("groupItemTitle") or "").strip() or None,
        "description": m.get("description") or ev.get("description"),
        "resolution_source": m.get("resolutionSource") or ev.get("resolutionSource") or None,
        "slug": m.get("slug"),
        "event_slug": ev_slug,
        "url": f"https://polymarket.com/event/{ev_slug}" if ev_slug else (f"https://polymarket.com/market/{m.get('slug')}" if m.get("slug") else None),
        "outcomes": outcomes,
        "outcome_prices": prices,
        "token_ids": tokens,
        "track_index": track_idx,
        "track_label": outcomes[track_idx] if outcomes else None,
        "track_token": tokens[track_idx] if len(tokens) > track_idx else None,
        "active": bool(m.get("active")),
        "closed": bool(m.get("closed")),
        "archived": bool(m.get("archived")),
        "start_ts": parse_ts(m.get("startDate") or m.get("startDateIso")),
        "end_ts": parse_ts(m.get("endDate") or m.get("endDateIso")),
        "closed_ts": parse_ts(m.get("closedTime")),
        "created_ts": parse_ts(m.get("createdAt")),
        "volume": _num(m.get("volumeNum")) if m.get("volumeNum") is not None else _num(m.get("volume")),
        "liquidity": _num(m.get("liquidityNum")) if m.get("liquidityNum") is not None else _num(m.get("liquidity")),
        "volume_24h": _num(m.get("volume24hr")),
        "best_bid": _num(m.get("bestBid")),
        "best_ask": _num(m.get("bestAsk")),
        "last_trade": _num(m.get("lastTradePrice")),
        "tags": tags,
        "resolution": res,
        "parse_errors": errors + res["errors"],
    }


def parse_event(e: dict) -> tuple[dict, list[dict]]:
    if not isinstance(e, dict) or not e.get("id"):
        raise ParseError("event without id")
    markets = []
    for m in e.get("markets") or []:
        try:
            markets.append(parse_market(m, e))
        except ParseError:
            continue
    ev = {
        "event_id": str(e["id"]),
        "title": (e.get("title") or "").strip(),
        "slug": e.get("slug"),
        "url": f"https://polymarket.com/event/{e['slug']}" if e.get("slug") else None,
        "description": e.get("description"),
        "resolution_source": e.get("resolutionSource") or None,
        "neg_risk": bool(e.get("negRisk") or e.get("enableNegRisk")),
        "end_ts": parse_ts(e.get("endDate")),
        "closed": bool(e.get("closed")),
        "closed_ts": parse_ts(e.get("closedTime")),
        "volume": _num(e.get("volume")),
        "liquidity": _num(e.get("liquidity")),
        "tags": [t.get("label") for t in (e.get("tags") or []) if isinstance(t, dict) and t.get("label")],
        "market_ids": [m["market_id"] for m in markets],
    }
    return ev, markets


def parse_price_history(payload) -> list[list]:
    """Parse CLOB /prices-history {"history":[{"t":int,"p":float}]} into sorted, de-duplicated [[t,p],...]."""
    if not isinstance(payload, dict) or not isinstance(payload.get("history"), list):
        raise ParseError("prices-history: missing 'history' array")
    pts = {}
    for row in payload["history"]:
        if not isinstance(row, dict):
            continue
        t, p = row.get("t"), _num(row.get("p"))
        if not isinstance(t, (int, float)) or p is None or not (0.0 <= p <= 1.0):
            continue
        pts[int(t)] = round(p, 6)
    return [[t, pts[t]] for t in sorted(pts)]
