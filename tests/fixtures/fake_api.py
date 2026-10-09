"""SYNTHETIC FIXTURE — NOT PRODUCTION DATA.

Deterministic fake Gamma/CLOB responses shaped exactly like the documented Polymarket API
(JSON-string encoded `outcomes`, `outcomePrices`, `clobTokenIds`, `umaResolutionStatuses`;
CLOB `{"history":[{"t":..,"p":..}]}`). All ids, prices and questions are invented for tests.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def ts(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def mk(mid, question, *, yes_price=None, closed=False, uma=None, uma_hist=None, end="2025-09-17T18:00:00Z",
       group=None, closed_time=None, volume=1000.0, outcomes=("Yes", "No"), prices=None, active=True):
    if prices is None:
        prices = [yes_price, round(1 - yes_price, 6)] if yes_price is not None else ["0.5", "0.5"]
    return {
        "id": str(mid), "question": question, "conditionId": f"0xc{mid}", "slug": f"m-{mid}",
        "outcomes": json.dumps(list(outcomes)), "outcomePrices": json.dumps([str(p) for p in prices]),
        "clobTokenIds": json.dumps([f"tok{mid}y", f"tok{mid}n"]), "closed": closed, "active": active and not closed,
        "umaResolutionStatus": uma, "umaResolutionStatuses": json.dumps(uma_hist or ([] if not uma else [uma])),
        "endDate": end, "closedTime": closed_time, "startDate": "2025-07-01T00:00:00Z",
        "createdAt": "2025-07-01T00:00:00Z", "groupItemTitle": group or "", "volumeNum": volume, "liquidityNum": 500.0,
        "volume24hr": 10.0, "bestBid": None, "bestAsk": None, "lastTradePrice": None,
        "description": f"FIXTURE resolution rules for {question}", "resolutionSource": "https://example.org/fixture",
    }


def ev(eid, title, markets, *, neg_risk=False, closed=False, end="2025-09-17T18:00:00Z"):
    return {"id": str(eid), "title": title, "slug": f"e-{eid}", "negRisk": neg_risk, "closed": closed, "endDate": end,
            "volume": sum(m["volumeNum"] for m in markets), "liquidity": 1000.0, "markets": markets,
            "description": "FIXTURE", "tags": [{"id": "1", "label": "Fixture"}]}


ANN = ts("2025-09-17T18:00:00Z")  # 14:00 EDT


def daily(start: str, end: str, f, hour=12, step=86400):
    out, t, e = [], ts(start) + hour * 3600, ts(end)
    while t <= e:
        out.append({"t": t, "p": round(f(t), 4)})
        t += step
    return out


def build():
    E, H = {}, {}
    # 1) Fed decision Sept 2025 (neg-risk, 4 outcomes, 25bp cut wins)
    labels = [("101", "No change", 0.0), ("102", "25 bps decrease", 1.0), ("103", "50+ bps decrease", 0.0), ("104", "25+ bps increase", 0.0)]
    ms = [mk(i, f"Will the Fed {g.lower()} after the September 2025 meeting?", group=g, closed=True, uma="resolved",
             prices=[w, 1 - w], closed_time="2025-09-17T19:30:00Z") for i, g, w in labels]
    E["9001"] = ev(9001, "Fed decision in September?", ms, neg_risk=True, closed=True)
    pre = {"101": 0.15, "102": 0.80, "103": 0.04, "104": 0.01}
    for i, _, w in labels:
        pts = daily("2025-07-15T00:00:00Z", "2025-09-17T00:00:00Z", lambda t, i=i: pre[i])
        pts += [{"t": ANN - 1800, "p": pre[i]}, {"t": ANN + 3600, "p": w if w else 0.001}]  # post-announcement point must be ignored
        H[f"tok{i}y"] = pts
    # 2) correlated standalone binary on same meeting
    m201 = mk(201, "Fed cuts rates in September 2025?", closed=True, uma="resolved", prices=[1, 0], volume=50.0, closed_time="2025-09-17T19:00:00Z")
    E["9002"] = ev(9002, "Fed rate cut in September 2025?", [m201], closed=True)
    H["tok201y"] = daily("2025-08-01T00:00:00Z", "2025-09-17T00:00:00Z", lambda t: 0.85)
    # 3) CLARITY Act signed in 2025? -> resolved NO
    m301 = mk(301, "Clarity Act signed into law in 2025?", closed=True, uma="resolved", prices=[0, 1], end="2025-12-31T23:59:00Z",
              volume=5000.0, closed_time="2026-01-01T10:00:00Z")
    E["9003"] = ev(9003, "Clarity Act signed into law in 2025?", [m301], closed=True, end="2025-12-31T23:59:00Z")
    H["tok301y"] = daily("2025-07-01T00:00:00Z", "2026-01-01T00:00:00Z", lambda t: 0.30 if t < ts("2025-11-01T00:00:00Z") else 0.10)
    # 6) duplicate of 3 (same question/end date, lower volume)
    m601 = mk(601, "Clarity Act signed into law in 2025?", closed=True, uma="resolved", prices=[0, 1], end="2025-12-31T23:59:00Z",
              volume=10.0, closed_time="2026-01-01T10:00:00Z")
    E["9006"] = ev(9006, "CLARITY Act law 2025", [m601], closed=True, end="2025-12-31T23:59:00Z")
    H["tok601y"] = daily("2025-07-01T00:00:00Z", "2026-01-01T00:00:00Z", lambda t: 0.5)
    # 4) open CLARITY Senate market with big 24h move
    now = ts("2026-10-09T12:00:00Z")
    m401 = mk(401, "Clarity Act passes Senate by December 31, 2026?", yes_price=0.62, end="2026-12-31T23:59:00Z", volume=8000.0)
    E["9004"] = ev(9004, "Clarity Act passes Senate in 2026?", [m401], end="2026-12-31T23:59:00Z")
    H["tok401y"] = [{"t": now - 10 * 86400, "p": 0.30}, {"t": now - 7 * 86400, "p": 0.35}, {"t": now - 86400, "p": 0.40}, {"t": now - 3600, "p": 0.62}]
    # 5) crypto price market — collected but never scored
    m501 = mk(501, "Bitcoin above $150k on December 31?", closed=True, uma="resolved", prices=[0, 1], end="2025-12-31T23:59:00Z")
    E["9005"] = ev(9005, "Bitcoin above $150k on December 31?", [m501], closed=True, end="2025-12-31T23:59:00Z")
    H["tok501y"] = daily("2025-11-01T00:00:00Z", "2025-12-31T00:00:00Z", lambda t: 0.2)
    # 7) upcoming Fed decision Oct 2026 (open neg-risk)
    up = [("701", "No change", 0.55), ("702", "25 bps increase", 0.40), ("703", "25 bps decrease", 0.05)]
    ms7 = [mk(i, f"Will the Fed {g.lower()} after the October 2026 meeting?", group=g, yes_price=p, end="2026-10-28T18:00:00Z") for i, g, p in up]
    E["9007"] = ev(9007, "Fed decision in October?", ms7, neg_risk=True, end="2026-10-28T18:00:00Z")
    for i, g, p in up:
        H[f"tok{i}y"] = [{"t": now - 8 * 86400, "p": p}, {"t": now - 2 * 86400, "p": p}, {"t": now - 7200, "p": p}]
    # 8) stablecoin bill YES before deadline -> settlement-onset reference
    m801 = mk(801, "Stablecoin bill signed into law by December 31, 2025?", closed=True, uma="resolved", prices=[1, 0],
              end="2025-12-31T23:59:00Z", closed_time="2025-07-20T00:00:00Z", volume=3000.0)
    E["9008"] = ev(9008, "Stablecoin bill signed into law in 2025?", [m801], closed=True, end="2025-12-31T23:59:00Z")
    H["tok801y"] = daily("2025-05-01T00:00:00Z", "2025-07-19T00:00:00Z", lambda t: 0.6) + \
        [{"t": ts("2025-07-18T20:00:00Z"), "p": 0.99}, {"t": ts("2025-07-19T12:00:00Z"), "p": 0.995}]
    # 9) invalid 50/50 macro market
    m901 = mk(901, "US recession in 2025?", closed=True, uma="resolved", prices=[0.5, 0.5], end="2025-12-31T23:59:00Z")
    E["9009"] = ev(9009, "US recession in 2025?", [m901], closed=True, end="2025-12-31T23:59:00Z")
    H["tok901y"] = daily("2025-06-01T00:00:00Z", "2025-12-31T00:00:00Z", lambda t: 0.3)
    return E, H, now


class FakeClient:
    """Implements Client.get_json for the endpoints the collector uses."""

    def __init__(self):
        self.events, self.history, self.now = build()
        self.requests = 0
        self.failures = 0
        self.fail_tokens: set[str] = set()

    def get_json(self, base, path, params=None):
        from pipeline.http import HttpError
        self.requests += 1
        params = params or {}
        if path == "/public-search":
            q = params["q"].lower()
            hits = [{"id": e["id"], "title": e["title"], "endDate": e["endDate"],
                     "markets": [{"question": m["question"]} for m in e["markets"]]}
                    for e in self.events.values() if any(w in e["title"].lower() for w in q.split())]
            return {"events": hits if params.get("page", 1) == 1 else [], "pagination": {"hasMore": False}}
        if path == "/events":
            return []
        if path.startswith("/events/"):
            eid = path.split("/")[-1]
            if eid not in self.events:
                raise HttpError(path, 404, "not found")
            return json.loads(json.dumps(self.events[eid]))
        if path == "/prices-history":
            tok = params["market"]
            if tok in self.fail_tokens:
                raise HttpError(path, 500, "fixture failure")
            pts = self.history.get(tok, [])
            if "startTs" in params and params.get("endTs", 0) - params["startTs"] > 15 * 86400:
                # mirrors the real CLOB: long windows are rejected
                raise HttpError(path, 400, '{"error":"invalid filters: \'startTs\' and \'endTs\' interval is too long"}')
            if "interval" in params:
                # mirrors the real CLOB at hourly fidelity: only about the last week comes back
                pts = [p for p in pts if p["t"] >= (pts[-1]["t"] - 7 * 86400)] if pts else []
            if "startTs" in params:
                pts = [p for p in pts if params["startTs"] <= p["t"] <= params.get("endTs", 1 << 40)]
            return {"history": pts}
        raise HttpError(path, 404, "unknown fixture path")
