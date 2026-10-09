"""Market discovery, metadata refresh, price snapshots and history ingestion."""
from __future__ import annotations

import time

from . import log
from .classify import Classifier, SCORED_CATEGORIES
from .config import Config
from .fomc import match_meeting
from .http import Client, HttpError
from .parse import ParseError, iso, parse_event, parse_price_history, parse_ts
from .store import Store

TERMINAL = {"final", "invalid"}


def event_kind(cls: dict, meeting: dict | None) -> str:
    if cls.get("subcategory") == "fomc_decision" and meeting:
        return "scheduled_announcement"
    if cls.get("category") == "macro" and cls.get("subcategory") in {"cpi", "core_cpi", "pce", "nonfarm_payrolls", "unemployment", "gdp"}:
        return "scheduled_release"
    return "deadline"


class Collector:
    def __init__(self, cfg: Config, client: Client | None = None, store: Store | None = None, now=None):
        self.cfg = cfg
        self.s = cfg.settings
        self.client = client or Client(self.s)
        self.store = store or Store(cfg.data_dir)
        self.cls = Classifier(cfg.rules, cfg.overrides)
        self.now = now or (lambda: int(time.time()))
        self.errors: list[dict] = []
        self.incomplete: list[dict] = []

    # ---------- API wrappers ----------
    def _gamma(self, path, params=None):
        return self.client.get_json(self.s["endpoints"]["gamma"], path, params)

    def _clob(self, path, params=None):
        return self.client.get_json(self.s["endpoints"]["clob"], path, params)

    def _err(self, where: str, e: Exception, **ctx):
        self.errors.append({"where": where, "error": str(e)[:300], **ctx})
        log.error(where, error=str(e)[:300], **ctx)

    # ---------- discovery ----------
    def _is_relevant_title(self, title: str, questions: list[str]) -> bool:
        probes = questions or [title]
        for q in probes:
            c = self.cls.classify(title, {"question": q, "group_item_title": None})
            if c["category"]:
                return True
        return False

    def discover_event_ids(self) -> dict[str, dict | None]:
        """Return {event_id: full_event_payload_or_None}. Payload present when listing returned full markets."""
        d = self.s["discovery"]
        found: dict[str, dict | None] = {}
        earliest = parse_ts(d["earliest_end_date"]) or 0

        for q in d["search_queries"]:
            for status in (None, "closed"):
                for page in range(1, d["max_search_pages"] + 1):
                    try:
                        res = self._gamma("/public-search", {"q": q, "page": page, "limit_per_type": d["search_limit_per_type"],
                                                           "keep_closed_markets": 1, "events_status": status,
                                                           "search_profiles": "false"})
                    except HttpError as e:
                        self._err("search", e, q=q, page=page, status=status)
                        break
                    evs = (res or {}).get("events") or []
                    for ev in evs:
                        if not isinstance(ev, dict) or not ev.get("id"):
                            continue
                        end = parse_ts(ev.get("endDate"))
                        if end and end < earliest:
                            continue
                        qs = [m.get("question") or "" for m in (ev.get("markets") or []) if isinstance(m, dict)]
                        if self._is_relevant_title(ev.get("title") or "", qs):
                            found.setdefault(str(ev["id"]), None)
                    if not ((res or {}).get("pagination") or {}).get("hasMore"):
                        break

        for slug in d["tag_slugs"]:
            for closed in ("false", "true"):
                for page in range(d["max_tag_pages"]):
                    try:
                        evs = self._gamma("/events", {"tag_slug": slug, "closed": closed, "limit": d["page_size"],
                                                      "offset": page * d["page_size"], "end_date_min": d["earliest_end_date"]})
                    except HttpError as e:
                        self._err("tag_listing", e, tag=slug, closed=closed, page=page)
                        break
                    if not isinstance(evs, list) or not evs:
                        break
                    for ev in evs:
                        if isinstance(ev, dict) and ev.get("id"):
                            qs = [m.get("question") or "" for m in (ev.get("markets") or []) if isinstance(m, dict)]
                            if self._is_relevant_title(ev.get("title") or "", qs):
                                found[str(ev["id"])] = ev if ev.get("markets") else found.get(str(ev["id"]))
                    if len(evs) < d["page_size"]:
                        break
        log.info("discovery_done", candidate_events=len(found))
        return found

    # ---------- registry update ----------
    def fetch_event(self, event_id: str) -> dict | None:
        try:
            ev = self._gamma(f"/events/{event_id}")
            if isinstance(ev, dict) and ev.get("id"):
                return ev
        except HttpError as e:
            if e.status != 404:
                self._err("fetch_event", e, event_id=event_id)
                return None
        try:  # fallback documented list filter
            evs = self._gamma("/events", {"id": event_id})
            return evs[0] if isinstance(evs, list) and evs else None
        except HttpError as e:
            self._err("fetch_event_fallback", e, event_id=event_id)
            return None

    def upsert_event(self, reg: dict, raw: dict) -> list[str]:
        now = self.now()
        try:
            ev, markets = parse_event(raw)
        except ParseError as e:
            self._err("parse_event", e, event_id=raw.get("id"))
            return []
        meeting = None
        changed = []
        tracked = []
        for m in markets:
            c = self.cls.classify(ev["title"], m)
            if not c["category"]:
                continue
            if c["category"] == "fed" and c["subcategory"] == "fomc_decision":
                meeting = meeting or match_meeting(ev["title"], ev["end_ts"] or m["end_ts"], self.cfg.fomc)
            prev = reg["markets"].get(m["market_id"], {})
            rec = {**m, "classification": c, "first_seen": prev.get("first_seen", now), "last_seen": now,
                   "retrieved_at": now, "status_history": prev.get("status_history", [])}
            st = m["resolution"]["status"]
            if not rec["status_history"] or rec["status_history"][-1]["status"] != st:
                rec["status_history"].append({"status": st, "observed_at": now, "uma": m["resolution"]["uma_status"]})
            reg["markets"][m["market_id"]] = rec
            tracked.append(m["market_id"])
            changed.append(m["market_id"])
        if not tracked:
            return []
        prev_ev = reg["events"].get(ev["event_id"], {})
        cats = {reg["markets"][i]["classification"]["category"] for i in tracked}
        main = reg["markets"][tracked[0]]["classification"]
        ev.update(
            tracked_market_ids=tracked,
            categories=sorted(cats),
            category=main["category"],
            subcategory=main["subcategory"],
            fomc_meeting_id=meeting["id"] if meeting else None,
            kind=event_kind(main, meeting),
            first_seen=prev_ev.get("first_seen", now),
            last_seen=now,
            retrieved_at=now,
        )
        reg["events"][ev["event_id"]] = ev
        return changed

    def snapshot_rows(self, reg: dict, market_ids: list[str]) -> list[dict]:
        now = self.now()
        rows = []
        for mid in market_ids:
            m = reg["markets"][mid]
            if m["closed"] or not m["outcome_prices"]:
                continue
            p = m["outcome_prices"][m["track_index"]] if len(m["outcome_prices"]) > m["track_index"] else None
            if p is None:
                continue
            rows.append({"t": now, "market_id": mid, "event_id": m["event_id"], "outcome": m["track_label"],
                         "p": p, "bid": m["best_bid"], "ask": m["best_ask"], "last": m["last_trade"],
                         "vol24h": m["volume_24h"], "liq": m["liquidity"], "src": "gamma.outcomePrices"})
        return rows

    # ---------- price history ----------
    def fetch_history(self, m: dict, full: bool) -> bool:
        token = m.get("track_token")
        if not token:
            self.incomplete.append({"market_id": m["market_id"], "reason": "no_clob_token"})
            return False
        h = self.s["history"]
        fid = h["fidelity_minutes"]
        now = self.now()
        existing = self.store.load_history(m["market_id"])
        pts: list[list] = []
        try:
            if existing and existing.get("points") and not full:
                start = existing["last_ts"] + 1
                pts = parse_price_history(self._clob("/prices-history", {"market": token, "startTs": start, "endTs": now, "fidelity": fid}))
            else:
                pts = parse_price_history(self._clob("/prices-history", {"market": token, "interval": "max", "fidelity": fid}))
                if not pts:
                    pts = self._chunked(token, m, fid, h["chunk_days"], now)
        except (HttpError, ParseError) as e:
            self._err("prices_history", e, market_id=m["market_id"])
            self.incomplete.append({"market_id": m["market_id"], "reason": "history_fetch_failed", "at": iso(now)})
            return False
        if not pts and not existing:
            self.incomplete.append({"market_id": m["market_id"], "reason": "empty_history", "at": iso(now)})
        self.store.merge_history(m["market_id"], token, m["track_label"], pts, now, fid, h["max_points_per_market"])
        return True

    def _chunked(self, token, m, fid, chunk_days, now) -> list[list]:
        start = m.get("start_ts") or m.get("created_ts") or ((m.get("end_ts") or now) - 365 * 86400)
        end = min(x for x in (m.get("closed_ts"), m.get("end_ts"), now) if x) + 86400
        end = min(end, now)
        out: dict[int, float] = {}
        t = start
        while t < end:
            t2 = min(t + chunk_days * 86400, end)
            for tt, p in parse_price_history(self._clob("/prices-history", {"market": token, "startTs": t, "endTs": t2, "fidelity": fid})):
                out[tt] = p
            t = t2
        return [[k, out[k]] for k in sorted(out)]

    # ---------- commands ----------
    def run_discover(self) -> dict:
        """Discover markets, refresh active ones, record snapshots and incremental history."""
        reg = self.store.load_registry()
        candidates = self.discover_event_ids()
        refreshed, changed = 0, []
        for eid, payload in candidates.items():
            known = reg["events"].get(eid)
            if known and known.get("frozen"):
                continue
            raw = payload or self.fetch_event(eid)
            if raw is None:
                continue
            changed += self.upsert_event(reg, raw)
            refreshed += 1
        # also refresh known open events that search may have missed this run
        for eid, ev in list(reg["events"].items()):
            if eid in candidates or ev.get("frozen") or ev.get("closed"):
                continue
            raw = self.fetch_event(eid)
            if raw:
                changed += self.upsert_event(reg, raw)
                refreshed += 1
        self.store.save_registry(reg)

        rows = self.snapshot_rows(reg, sorted(set(changed)))
        month = time.strftime("%Y-%m", time.gmtime(self.now()))
        written = self.store.append_snapshots(rows, month)

        hist_ok = 0
        for mid in sorted(set(changed)):
            m = reg["markets"][mid]
            if m["classification"].get("excluded"):
                continue
            if not m["closed"]:
                hist_ok += self.fetch_history(m, full=False)
        return {"candidate_events": len(candidates), "events_refreshed": refreshed,
                "markets_tracked": len(reg["markets"]), "snapshots_written": written, "histories_updated": hist_ok}

    def run_resolve(self) -> dict:
        """Re-check closed / pending events; fetch final full history once a market closes; freeze when done."""
        reg = self.store.load_registry()
        checked, froze, hist = 0, 0, 0
        now = self.now()
        for eid, ev in list(reg["events"].items()):
            if ev.get("frozen"):
                continue
            mids = ev.get("tracked_market_ids", [])
            statuses = [reg["markets"][m]["resolution"]["status"] for m in mids if m in reg["markets"]]
            due = ev.get("closed") or any(s != "unresolved" for s in statuses) or \
                any((reg["markets"][m].get("end_ts") or now + 1) < now for m in mids if m in reg["markets"])
            if not due:
                continue
            raw = self.fetch_event(eid)
            if raw is None:
                continue
            self.upsert_event(reg, raw)
            checked += 1
            ev = reg["events"][eid]
            all_done = True
            for mid in ev["tracked_market_ids"]:
                m = reg["markets"][mid]
                if m["classification"].get("excluded"):
                    continue
                if m["closed"]:
                    hrec = self.store.load_history(mid)
                    if not hrec or (hrec.get("retrieved_at") or 0) <= (m.get("closed_ts") or now):
                        ok = self.fetch_history(m, full=True)
                        hist += ok
                        all_done &= ok
                if m["resolution"]["status"] not in TERMINAL:
                    all_done = False
            if all_done:
                ev["frozen"] = True
                ev["frozen_at"] = now
                froze += 1
        self.store.save_registry(reg)
        return {"events_checked": checked, "events_frozen": froze, "histories_fetched": hist}

    def run_backfill(self, limit: int | None = None) -> dict:
        """Fetch full history for every tracked market lacking any stored history."""
        reg = self.store.load_registry()
        done = 0
        for mid, m in sorted(reg["markets"].items()):
            if limit is not None and done >= limit:
                break
            if m["classification"].get("excluded") or self.store.load_history(mid):
                continue
            done += self.fetch_history(m, full=True)
        return {"histories_backfilled": done}


def scored_category(m: dict) -> bool:
    return m["classification"]["category"] in SCORED_CATEGORIES and not m["classification"].get("excluded")
