"""Build all derived analytics consumed by the dashboard. Deterministic given the stored data.

Scoring units (to prevent double counting):
  * multiclass unit  - a negRisk (mutually exclusive) event whose tracked markets form the full outcome set
                       and resolve with exactly one YES. Scored with the multiclass Brier score.
  * binary_set unit  - any other event: each final market is scored with the binary Brier score and the
                       event's score is the MEAN over its markets (one event = one unit, weight 1).
  * FOMC de-duplication - all units mapped to the same official FOMC meeting collapse to ONE primary unit
                       (multiclass preferred, then highest volume); the rest are kept but flagged
                       `correlated_with` and excluded from headline aggregates.
  * duplicate markets (same normalized question + end date) are excluded; canonical = highest volume.
"""
from __future__ import annotations

import csv
import io
import re
import time
from collections import defaultdict
from datetime import datetime, timezone

from . import metrics as M
from .classify import SCORED_CATEGORIES, find_duplicates
from .config import Config
from .classify import Classifier
from .collect import event_kind
from .fomc import announcement_ts, match_meeting, verify_fed_market
from .parse import iso, parse_ts
from .store import Store, write_json, atomic_write
from .timing import forecast_at, reference_time, value_at_or_before

CLARITY_MILESTONES = [
    ("presidential_signature", r"\bsign(ed|s)?\b|into law|\bveto"),
    ("final_congressional_passage", r"pass(es|ed)? (both|congress)|clear(s|ed)? congress|congress pass"),
    ("senate_passage", r"\bsenate\b.*\bpass|pass.*\bsenate\b"),
    ("house_passage", r"\bhouse\b.*\bpass|pass.*\bhouse\b"),
    ("committee_approval", r"committee|markup|advance"),
    ("enactment_by_deadline", r"\b(law|enacted|become law)\b"),
]


def clarity_milestone(q: str) -> str:
    t = (q or "").lower()
    for key, pat in CLARITY_MILESTONES:
        if re.search(pat, t):
            return key
    return "other"


def quarter(ts: int) -> str:
    d = datetime.fromtimestamp(ts, timezone.utc)
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


class Analyzer:
    def __init__(self, cfg: Config, store: Store | None = None, now: int | None = None):
        self.cfg = cfg
        self.s = cfg.settings
        self.store = store or Store(cfg.data_dir)
        self.now = now or int(time.time())
        self.hz = self.s["horizons"]
        self.ms = self.s["metrics"]
        self._hist_cache: dict[str, list] = {}

    # ------------------------------------------------------------------ helpers
    def points(self, mid: str) -> list[list]:
        if mid not in self._hist_cache:
            h = self.store.load_history(mid)
            self._hist_cache[mid] = (h or {}).get("points", [])
        return self._hist_cache[mid]

    def series_with_snapshots(self, mid: str, snaps: dict[str, list]) -> list[list]:
        merged = {t: p for t, p in self.points(mid)}
        for t, p in snaps.get(mid, []):
            merged.setdefault(t, p)
        return [[t, merged[t]] for t in sorted(merged)]

    def forecasts(self, mid: str, ref: int) -> dict:
        out = {}
        pts = self.points(mid)
        for h in self.hz:
            target = ref - h["seconds"]
            if target > self.now:
                out[h["key"]] = {"status": "future", "target_ts": target}
                continue
            out[h["key"]] = forecast_at(pts, ref, h["seconds"], h["max_staleness_seconds"], self.s["final_buffer_seconds"])
        return out

    def market_ref(self, m: dict, ev: dict, sched: int | None) -> tuple[int | None, str]:
        ov = (self.cfg.overrides.get("markets", {}).get(m["market_id"]) or {}).get("reference_time") or \
             (self.cfg.overrides.get("events", {}).get(m["event_id"] or "") or {}).get("reference_time")
        return reference_time(m, ev.get("kind", "deadline"), sched, self.points(m["market_id"]),
                              self.s["settlement_band"], parse_ts(ov) if ov else None)

    @staticmethod
    def quality(m: dict, verification: dict | None) -> str:
        if verification and verification.get("status") == "verified":
            return "A"
        if m["resolution"].get("basis") == "uma_resolved":
            return "B"
        return "C"

    # ------------------------------------------------------------------ main
    def run(self) -> dict:
        reg = self.store.load_registry()
        meetings = {mt["id"]: mt for mt in self.cfg.fomc["meetings"]}
        markets, events = self.reclassify(reg)

        dups = find_duplicates([m for m in markets.values() if not m["classification"].get("excluded")])

        snaps: dict[str, list] = defaultdict(list)
        for r in self.store.iter_snapshots():
            if r.get("p") is not None:
                snaps[r["market_id"]].append((int(r["t"]), float(r["p"])))

        market_rows: dict[str, dict] = {}
        units: list[dict] = []

        for eid, ev in events.items():
            mids = [i for i in ev.get("tracked_market_ids", []) if i in markets]
            meeting = meetings.get(ev.get("fomc_meeting_id")) if ev.get("fomc_meeting_id") else None
            sched = announcement_ts(meeting, self.cfg.fomc) if meeting and ev.get("kind") == "scheduled_announcement" else None

            refs = {mid: self.market_ref(markets[mid], ev, sched) for mid in mids}
            if ev.get("neg_risk") and refs:
                # Mutually exclusive outcomes share one information set: once any outcome is known,
                # every sibling's price is post-event. Use the earliest reference across the event.
                known = [r for r in refs.values() if r[0]]
                if known:
                    earliest = min(known, key=lambda r: r[0])
                    refs = {mid: (earliest[0], earliest[1] if r[0] == earliest[0] else f"event_min:{earliest[1]}")
                            for mid, r in refs.items()}

            for mid in mids:
                m = markets[mid]
                ref, method = refs[mid]
                ver = None
                if m["classification"]["subcategory"] == "fomc_decision":
                    ver = verify_fed_market(m, meeting)
                ext = (self.cfg.overrides.get("markets", {}).get(mid) or {}).get("external_source")
                fc = self.forecasts(mid, ref) if ref else {}
                res = m["resolution"]
                o = None
                if res["status"] == "final":
                    o = int(res["winner_index"] == m["track_index"])
                scores = {}
                for k, f in fc.items():
                    if f.get("status") == "ok" and o is not None:
                        scores[k] = M.brier_binary(f["p"], o)
                flags = []
                if mid in dups:
                    flags.append("duplicate")
                if res.get("was_disputed"):
                    flags.append("disputed_during_resolution")
                if "settlement_onset" in method:
                    flags.append("reference_time_estimated_from_price_path")
                if method in ("end_date", "closed_time") and ev.get("kind") == "scheduled_release":
                    flags.append("reference_time_is_market_end_date")
                if ver and ver["status"] == "conflict":
                    flags.append("external_verification_conflict")
                if m.get("parse_errors"):
                    flags.append("parse_warnings")
                if not self.points(mid):
                    flags.append("no_price_history")
                pts = self.points(mid)
                vol30 = M.path_volatility(pts, ref - 30 * 86400, ref) if ref and pts else None
                twm = M.time_weighted_mean(pts, ref - 30 * 86400, ref) if ref and pts else None
                series = self.series_with_snapshots(mid, snaps)
                cur_p = m["outcome_prices"][m["track_index"]] if len(m.get("outcome_prices") or []) > m["track_index"] else None
                completeness = sum(1 for f in fc.values() if f.get("status") == "ok") / len(self.hz) if fc else 0.0
                market_rows[mid] = {
                    "market_id": mid, "event_id": eid, "question": m["question"], "group_item_title": m["group_item_title"],
                    "event_title": ev["title"], "category": m["classification"]["category"],
                    "subcategory": m["classification"]["subcategory"], "relevance": m["classification"]["relevance"],
                    "rule_id": m["classification"]["rule_id"], "override": m["classification"].get("override"),
                    "excluded": m["classification"].get("excluded", False),
                    "scored_category": m["classification"]["category"] in SCORED_CATEGORIES,
                    "url": m["url"] or ev.get("url"), "outcomes": m["outcomes"], "tracked_outcome": m["track_label"],
                    "status": res["status"], "resolution_basis": res["basis"], "uma_status": res["uma_status"],
                    "winner": res["winner_label"], "outcome_value": o,
                    "status_history": m.get("status_history", []),
                    "current_p": cur_p if not m["closed"] else None,
                    "final_settlement_prices": m["outcome_prices"] if m["closed"] else None,
                    "end_ts": m["end_ts"], "closed_ts": m["closed_ts"], "start_ts": m["start_ts"],
                    "reference_ts": ref, "reference_method": method,
                    "volume": m["volume"], "liquidity": m["liquidity"], "volume_24h": m["volume_24h"],
                    "forecasts": fc, "brier": scores, "volatility_30d": vol30, "time_weighted_p_30d": twm,
                    "resolution_source": m.get("resolution_source"), "description": m.get("description"),
                    "external_verification": ver, "external_source": ext or (ver or {}).get("source"),
                    "duplicate_of": dups.get(mid), "quality": self.quality(m, ver) if res["status"] == "final" else None,
                    "flags": flags, "completeness": round(completeness, 3),
                    "n_history_points": len(pts), "first_obs_ts": pts[0][0] if pts else None,
                    "last_obs_ts": series[-1][0] if series else None,
                    "retrieved_at": m.get("retrieved_at"), "fomc_meeting_id": ev.get("fomc_meeting_id"),
                    "clarity_milestone": clarity_milestone(m["question"]) if m["classification"]["subcategory"] == "clarity_act" else None,
                    "correlated_with": None,
                }

            units.extend(self.build_units(ev, mids, markets, market_rows))

        self.dedupe_fed(units, market_rows)
        self.apply_baselines(units, market_rows)

        perf = self.performance(units, market_rows)
        shifts = self.shifts(markets, snaps, market_rows)
        fed = self.fed_view(events, market_rows, units, meetings, shifts)
        regulation = self.regulation_view(market_rows, events)
        status = self.status_view(reg, market_rows)

        out_dir = self.store.root / "derived"
        cv = self.cfg.calc_version
        meta = {"generated_at": iso(self.now), "calc_version": cv,
                "rules_version": self.cfg.rules.get("version"), "fomc_transcribed_at": self.cfg.fomc.get("transcribed_at")}
        index = sorted(market_rows.values(), key=lambda r: -(r["end_ts"] or 0))
        write_json(out_dir / "markets.json", {**meta, "markets": index}, compact=True)
        write_json(out_dir / "units.json", {**meta, "units": units}, compact=True)
        write_json(out_dir / "performance.json", {**meta, **perf})
        write_json(out_dir / "shifts.json", {**meta, **shifts})
        write_json(out_dir / "fed.json", {**meta, **fed})
        write_json(out_dir / "regulation.json", {**meta, **regulation})
        write_json(out_dir / "status.json", {**meta, **status})
        summary = self.summary(meta, market_rows, units, perf, shifts, status)
        write_json(out_dir / "summary.json", summary)
        self.exports(out_dir, meta, market_rows, units, perf)
        return {"markets": len(market_rows), "units": len(units),
                "scored_units": sum(1 for u in units if u["primary"] and u["scores"])}

    def reclassify(self, reg: dict) -> tuple[dict, dict]:
        """Re-apply the CURRENT rules, overrides and FOMC calendar to every stored market (in memory only),
        so rule changes take effect retroactively, including for frozen events that are never re-fetched.
        Markets whose rule is `skip` (or that no longer match any rule) are dropped from the analysis."""
        cls = Classifier(self.cfg.rules, self.cfg.overrides)
        markets, events = {}, {}
        for eid, ev in reg["events"].items():
            kept = []
            meeting = None
            for mid in ev.get("tracked_market_ids", []):
                m = reg["markets"].get(mid)
                if not m:
                    continue
                c = cls.classify(ev.get("title", ""), m)
                if not c["category"]:
                    continue
                if c["subcategory"] == "fomc_decision" and meeting is None:
                    meeting = match_meeting(ev.get("title", ""), ev.get("end_ts") or m.get("end_ts"), self.cfg.fomc)
                markets[mid] = {**m, "classification": c}
                kept.append(mid)
            if not kept:
                continue
            main = markets[kept[0]]["classification"]
            events[eid] = {**ev, "tracked_market_ids": kept, "category": main["category"], "subcategory": main["subcategory"],
                           "fomc_meeting_id": meeting["id"] if meeting else None, "kind": event_kind(main, meeting)}
        return markets, events

    # ------------------------------------------------------------------ units
    def build_units(self, ev: dict, mids: list[str], markets: dict, rows: dict) -> list[dict]:
        cand = [mid for mid in mids if rows[mid]["scored_category"] and not rows[mid]["excluded"]
                and not rows[mid]["duplicate_of"]]
        if not cand:
            return []
        statuses = [rows[m]["status"] for m in cand]
        base = {"event_id": ev["event_id"], "event_title": ev["title"], "url": ev.get("url"),
                "category": rows[cand[0]]["category"], "subcategory": rows[cand[0]]["subcategory"],
                "fomc_meeting_id": ev.get("fomc_meeting_id"), "volume": ev.get("volume"),
                "primary": True, "correlated_with": None, "exclusion_reason": None}

        full_set = set(cand) == set(ev.get("market_ids", [])) and len(cand) >= 2
        if ev.get("neg_risk") and full_set:
            unit = {**base, "unit_id": f"E{ev['event_id']}", "type": "multiclass", "market_ids": cand,
                    "labels": [rows[m]["group_item_title"] or rows[m]["question"] for m in cand]}
            if any(s in ("invalid", "closed_unverified") for s in statuses):
                unit.update(status="not_scoreable", exclusion_reason="invalid_or_unverified_outcome", scores={})
                return [unit]
            if any(s != "final" for s in statuses):
                unit.update(status="pending", scores={})
                return [unit]
            yes = [i for i, m in enumerate(cand) if rows[m]["outcome_value"] == 1]
            if len(yes) != 1:
                unit.update(status="not_scoreable", exclusion_reason="not_exactly_one_winner", scores={})
                return [unit]
            if any("external_verification_conflict" in rows[m]["flags"] for m in cand):
                unit.update(status="not_scoreable", exclusion_reason="external_verification_conflict", scores={})
                return [unit]
            winner = yes[0]
            refs = [rows[m]["reference_ts"] for m in cand if rows[m]["reference_ts"]]
            ref = min(refs) if refs else None
            unit.update(status="final", winner_index=winner, winner_label=unit["labels"][winner], reference_ts=ref,
                        reference_method=rows[cand[winner]]["reference_method"], K=len(cand), scores={}, forecasts={},
                        quality=min(rows[m]["quality"] or "C" for m in cand))
            for h in self.hz:
                k = h["key"]
                fcs = [forecast_at(self.points(m), ref, h["seconds"], h["max_staleness_seconds"], self.s["final_buffer_seconds"]) for m in cand]
                if any(f["status"] != "ok" for f in fcs):
                    reasons = sorted({f.get("reason", "?") for f in fcs if f["status"] != "ok"})
                    unit["forecasts"][k] = {"status": "missing", "reasons": reasons}
                    continue
                raw = [f["p"] for f in fcs]
                try:
                    norm, s = M.normalize(raw)
                except ValueError:
                    unit["forecasts"][k] = {"status": "missing", "reasons": ["zero_sum"]}
                    continue
                bs = M.brier_multiclass(norm, winner)
                unit["forecasts"][k] = {"status": "ok", "raw": raw, "normalized": [round(x, 6) for x in norm], "raw_sum": round(s, 6),
                                        "obs_ts": [f["obs_ts"] for f in fcs], "log_loss": M.log_loss_multiclass(norm, winner, self.ms["log_loss_clip"]),
                                        "top_correct": int(max(range(len(norm)), key=lambda i: norm[i]) == winner)}
                unit["scores"][k] = bs
            return [unit]

        unit = {**base, "unit_id": f"E{ev['event_id']}", "type": "binary_set", "market_ids": cand,
                "labels": [rows[m]["question"] for m in cand], "scores": {}, "forecasts": {}}
        final = [m for m in cand if rows[m]["status"] == "final" and "external_verification_conflict" not in rows[m]["flags"]]
        if not final:
            if all(s in ("invalid", "closed_unverified") for s in statuses):
                unit.update(status="not_scoreable", exclusion_reason="invalid_or_unverified_outcome")
            else:
                unit.update(status="pending")
            return [unit]
        unit["status"] = "final"
        unit["scored_market_ids"] = final
        refs = [rows[m]["reference_ts"] for m in final if rows[m]["reference_ts"]]
        unit["reference_ts"] = min(refs) if refs else None
        unit["quality"] = min(rows[m]["quality"] or "C" for m in final)
        for h in self.hz:
            k = h["key"]
            vals = [rows[m]["brier"][k] for m in final if k in rows[m]["brier"]]
            if vals and len(vals) == len(final):
                unit["scores"][k] = M.mean(vals)
                unit["forecasts"][k] = {"status": "ok", "n_markets": len(vals)}
            else:
                unit["forecasts"][k] = {"status": "missing", "reasons": ["one_or_more_markets_missing"]}
        return [unit]

    def dedupe_fed(self, units: list[dict], rows: dict) -> None:
        by_meeting = defaultdict(list)
        for u in units:
            if u.get("fomc_meeting_id") and u["category"] == "fed" and u["subcategory"] == "fomc_decision":
                by_meeting[u["fomc_meeting_id"]].append(u)
        for mid, us in by_meeting.items():
            if len(us) < 2:
                continue
            us.sort(key=lambda u: (u["type"] != "multiclass", -(u.get("volume") or 0)))
            for u in us[1:]:
                u["primary"] = False
                u["correlated_with"] = us[0]["unit_id"]
                for m in u["market_ids"]:
                    rows[m]["correlated_with"] = us[0]["unit_id"]

    def apply_baselines(self, units: list[dict], rows: dict) -> None:
        """Uniform baseline for every unit; expanding-window base-rate baseline for binary units.

        Base rate for a market forecast made at t_f uses ONLY outcomes of same-subcategory markets whose
        reference time is < t_f (Laplace-smoothed (k+1)/(n+2)), so the baseline has no look-ahead either.
        """
        history = sorted(((r["reference_ts"], r["subcategory"], r["outcome_value"]) for r in rows.values()
                          if r["outcome_value"] is not None and r["reference_ts"] and r["scored_category"]
                          and not r["duplicate_of"] and not r["excluded"]), key=lambda x: x[0])

        def base_rate(sub: str, t_f: int) -> tuple[float, int]:
            k = n = 0
            for t, s, o in history:
                if t >= t_f:
                    break
                if s == sub:
                    n += 1
                    k += o
            return (k + 1) / (n + 2), n

        for u in units:
            u["baseline_uniform"] = {}
            u["baseline_base_rate"] = {}
            if u.get("status") != "final":
                continue
            for h in self.hz:
                k = h["key"]
                if k not in u["scores"]:
                    continue
                if u["type"] == "multiclass":
                    K = u["K"]
                    u["baseline_uniform"][k] = 1 - 1 / K
                else:
                    u["baseline_uniform"][k] = 0.25
                    vals = []
                    for mid in u["scored_market_ids"]:
                        r = rows[mid]
                        t_f = r["reference_ts"] - h["seconds"]
                        p, n = base_rate(r["subcategory"], t_f)
                        vals.append(M.brier_binary(p, r["outcome_value"]))
                    u["baseline_base_rate"][k] = M.mean(vals)

    # ------------------------------------------------------------------ performance
    def performance(self, units: list[dict], rows: dict) -> dict:
        seed, B = self.ms["random_seed"], self.ms["bootstrap_samples"]
        prim = [u for u in units if u["primary"] and u.get("status") == "final"]
        horizons = [h["key"] for h in self.hz]

        def agg(us: list[dict], k: str) -> dict:
            out = {}
            for typ in ("binary_set", "multiclass"):
                sel = [u for u in us if u["type"] == typ and k in u["scores"]]
                sc = [u["scores"][k] for u in sel]
                ci = M.bootstrap_mean_ci(sc, B, seed)
                uni = [u["baseline_uniform"][k] for u in sel]
                bss = M.skill_score(sc, uni)
                bss_ci = M.bootstrap_skill_ci(sc, uni, B, seed)
                entry = {"n_events": len(sc), "mean_brier": M.mean(sc), "ci95": ci,
                         "bss_vs_uniform": bss, "bss_vs_uniform_ci95": bss_ci}
                if typ == "binary_set":
                    br = [u["baseline_base_rate"].get(k) for u in sel]
                    if all(x is not None for x in br) and sc:
                        entry["bss_vs_base_rate"] = M.skill_score(sc, br)
                        entry["bss_vs_base_rate_ci95"] = M.bootstrap_skill_ci(sc, br, B, seed)
                        entry["mean_brier_base_rate"] = M.mean(br)
                out[typ] = entry
            # pooled skill (scale-free) across types
            allsel = [u for u in us if k in u["scores"]]
            out["pooled_bss_vs_uniform"] = M.skill_score([u["scores"][k] for u in allsel], [u["baseline_uniform"][k] for u in allsel])
            out["n_events"] = len(allsel)
            return out

        by_h = {k: agg(prim, k) for k in horizons}
        cats = sorted({u["category"] for u in prim})
        by_cat = {c: {k: agg([u for u in prim if u["category"] == c], k) for k in horizons} for c in cats}
        subs = sorted({(u["category"], u["subcategory"]) for u in prim})
        by_sub = [{"category": c, "subcategory": s, "by_horizon": {k: agg([u for u in prim if u["subcategory"] == s], k) for k in ("7d", "final")}} for c, s in subs]

        # market-level (binary) metrics & calibration: one forecast per market per horizon
        prim_markets = set()
        for u in prim:
            prim_markets.update(u.get("scored_market_ids") or u["market_ids"])
        mlevel = {}
        calib = {}
        for h in self.hz:
            k = h["key"]
            pairs = [(rows[m]["forecasts"][k]["p"], rows[m]["outcome_value"]) for m in sorted(prim_markets)
                     if rows[m]["outcome_value"] is not None and rows[m]["forecasts"].get(k, {}).get("status") == "ok"]
            bins = M.calibration_bins(pairs, self.ms["calibration_bins"], self.ms["min_bin_n_for_inference"])
            calib[k] = {"n": len(pairs), "bins": bins, "ece": M.expected_calibration_error(bins)}
            if not pairs:
                mlevel[k] = {"n": 0}
                continue
            bs = [M.brier_binary(p, o) for p, o in pairs]
            ll = [M.log_loss_binary(p, o, self.ms["log_loss_clip"]) for p, o in pairs]
            dirs = [M.directional(p, o, self.ms["directional_threshold"], self.ms["no_call_band"]) for p, o in pairs]
            called = [d for d in dirs if d is not None]
            mlevel[k] = {
                "n": len(pairs), "mean_brier": M.mean(bs), "brier_ci95": M.bootstrap_mean_ci(bs, B, seed),
                "log_loss": M.mean(ll), "mae": M.mean([abs(p - o) for p, o in pairs]),
                "directional_accuracy": M.mean(called) if called else None,
                "directional_coverage": len(called) / len(pairs),
                "base_rate_yes": M.mean([o for _, o in pairs]),
                "bss_vs_0_5": M.skill_score(bs, [0.25] * len(bs)),
            }

        # trend by quarter of reference time
        trend = []
        for k in ("7d", "final"):
            byq = defaultdict(list)
            for u in prim:
                if k in u["scores"] and u.get("reference_ts"):
                    byq[quarter(u["reference_ts"])].append(u)
            for q in sorted(byq):
                us = byq[q]
                trend.append({"horizon": k, "quarter": q, "n_events": len(us),
                              "pooled_bss_vs_uniform": M.skill_score([u["scores"][k] for u in us], [u["baseline_uniform"][k] for u in us]),
                              "mean_brier_binary": M.mean([u["scores"][k] for u in us if u["type"] == "binary_set"]),
                              "mean_brier_multiclass": M.mean([u["scores"][k] for u in us if u["type"] == "multiclass"]),
                              "low_sample": len(us) < self.ms["min_events_for_trend_point"]})

        # coverage diagnostics
        final_units = [u for u in units if u.get("status") == "final" and u["primary"]]
        coverage = {}
        for h in self.hz:
            k = h["key"]
            reasons = defaultdict(int)
            ok = 0
            for u in final_units:
                f = u["forecasts"].get(k, {})
                if f.get("status") == "ok":
                    ok += 1
                else:
                    for r in f.get("reasons", ["unknown"]):
                        reasons[r] += 1
            coverage[k] = {"units_final": len(final_units), "units_with_forecast": ok, "missing_reasons": dict(reasons)}
        status_counts = defaultdict(int)
        for u in units:
            status_counts[f"{u['status']}{'' if u['primary'] else ' (correlated, not primary)'}"] += 1
        excl = defaultdict(int)
        for u in units:
            if u.get("exclusion_reason"):
                excl[u["exclusion_reason"]] += 1
        quality = defaultdict(int)
        for u in prim:
            quality[u.get("quality", "C")] += 1

        return {
            "horizons": horizons, "by_horizon": by_h, "by_category": by_cat, "by_subcategory": by_sub,
            "market_level": mlevel, "calibration": calib, "trend": trend, "coverage": coverage,
            "unit_status_counts": dict(status_counts), "exclusions": dict(excl), "quality_counts": dict(quality),
            "n_primary_scored_events": len(prim),
            "independence_caveat": "Event-level units are treated as independent for confidence intervals. Different events can share drivers (e.g. consecutive FOMC meetings, a CPI print and the next Fed decision), so true uncertainty is likely wider than shown.",
        }

    # ------------------------------------------------------------------ shifts
    def shifts(self, markets: dict, snaps: dict, rows: dict) -> dict:
        sh = self.s["shifts"]
        out = []
        for mid, m in markets.items():
            r = rows.get(mid)
            if not r or m["closed"] or r["excluded"]:
                continue
            series = self.series_with_snapshots(mid, snaps)
            if not series:
                continue
            cur_t, cur_p = series[-1]
            if r["current_p"] is not None and (m.get("retrieved_at") or 0) >= cur_t:
                cur_t, cur_p = m["retrieved_at"], r["current_p"]

            def chg(sec, tol):
                v = value_at_or_before(series, cur_t - sec, tol)
                if not v:
                    return None
                t0, p0 = v
                pp = (cur_p - p0) * 100
                rel = ((cur_p - p0) / p0 * 100) if p0 >= sh["min_base_for_relative"] else None
                return {"past_p": p0, "past_ts": t0, "pp_change": round(pp, 3), "relative_change_pct": None if rel is None else round(rel, 2)}

            d24 = chg(86400, sh["tolerance_24h_seconds"])
            d7 = chg(7 * 86400, sh["tolerance_7d_seconds"])
            flag24 = bool(d24 and abs(d24["pp_change"]) >= sh["pp_threshold_24h"])
            flag7 = bool(d7 and abs(d7["pp_change"]) >= sh["pp_threshold_7d"])
            out.append({"market_id": mid, "event_id": m["event_id"], "question": m["question"],
                        "label": m["group_item_title"], "event_title": r["event_title"],
                        "category": r["category"], "subcategory": r["subcategory"], "relevance": r["relevance"],
                        "current_p": cur_p, "current_ts": cur_t, "d24h": d24, "d7d": d7,
                        "flag_24h": flag24, "flag_7d": flag7, "volume": m["volume"], "liquidity": m["liquidity"],
                        "volume_24h": m["volume_24h"], "end_ts": m["end_ts"], "url": r["url"]})
        out.sort(key=lambda x: -abs((x["d24h"] or {}).get("pp_change") or 0))
        return {"thresholds": {"pp_24h": sh["pp_threshold_24h"], "pp_7d": sh["pp_threshold_7d"]},
                "note": "Changes are in percentage points (pp). Relative change = (now - past) / past. A flag is a research signal, not a trade recommendation.",
                "markets": out}

    # ------------------------------------------------------------------ views
    def fed_view(self, events: dict, rows: dict, units: list, meetings: dict, shifts: dict) -> dict:
        unit_by_event = {u["event_id"]: u for u in units}
        shift_by_m = {s["market_id"]: s for s in shifts["markets"]}
        out = []
        for mid_, mt in sorted(meetings.items()):
            evs = [e for e in events.values() if e.get("fomc_meeting_id") == mid_]
            ann = announcement_ts(mt, self.cfg.fomc)
            ev_out = []
            for e in evs:
                u = unit_by_event.get(e["event_id"])
                outcomes = []
                for m in e.get("tracked_market_ids", []):
                    r = rows.get(m)
                    if not r or r["subcategory"] != "fomc_decision":
                        continue
                    outcomes.append({"market_id": m, "label": r["group_item_title"] or r["question"],
                                     "probabilities": {k: (f.get("p") if f.get("status") == "ok" else None) for k, f in r["forecasts"].items()},
                                     "missing": {k: f.get("reason") or f.get("status") for k, f in r["forecasts"].items() if f.get("status") != "ok"},
                                     "current_p": r["current_p"], "status": r["status"], "outcome_value": r["outcome_value"],
                                     "verification": r["external_verification"], "shift": shift_by_m.get(m)})
                if outcomes:
                    ev_out.append({"event_id": e["event_id"], "title": e["title"], "url": e.get("url"), "neg_risk": e.get("neg_risk"),
                                   "volume": e.get("volume"), "unit": {k: u.get(k) for k in ("unit_id", "type", "status", "primary", "correlated_with", "scores", "baseline_uniform", "exclusion_reason")} if u else None,
                                   "outcomes": outcomes})
            out.append({**mt, "announcement_ts": ann, "is_past": ann < self.now, "events": ev_out})
        upcoming = next((m for m in out if not m["is_past"]), None)
        fed_units = [u for u in units if u["category"] == "fed" and u["subcategory"] == "fomc_decision" and u["primary"] and u.get("status") == "final"]
        lead = {}
        for h in self.hz:
            k = h["key"]
            sel = [u for u in fed_units if k in u["scores"]]
            lead[k] = {"n_events": len(sel), "mean_brier": M.mean([u["scores"][k] for u in sel]),
                       "bss_vs_uniform": M.skill_score([u["scores"][k] for u in sel], [u["baseline_uniform"][k] for u in sel]),
                       "types": sorted({u["type"] for u in sel})}
        return {"official_sources": (self.cfg.official_sources or {}).get("subcategories", {}).get("fomc_decision", []),
                "meetings": out, "upcoming_meeting_id": upcoming["id"] if upcoming else None, "brier_by_lead_time": lead,
                "other_fed_markets": [self._brief(r) for r in rows.values() if r["category"] == "fed" and r["subcategory"] != "fomc_decision"]}

    @staticmethod
    def _brief(r: dict) -> dict:
        return {k: r.get(k) for k in ("market_id", "event_id", "question", "group_item_title", "event_title", "subcategory", "status",
                                      "current_p", "winner", "end_ts", "url", "brier", "relevance", "clarity_milestone",
                                      "external_source", "quality", "flags", "volume")}

    def regulation_view(self, rows: dict, events: dict) -> dict:
        reg = [r for r in rows.values() if r["category"] in ("crypto_regulation", "crypto_events") and not r["excluded"]]
        groups = defaultdict(list)
        for r in reg:
            groups[(r["category"], r["subcategory"])].append(self._brief(r))
        clarity = defaultdict(list)
        for r in reg:
            if r["subcategory"] == "clarity_act":
                clarity[r["clarity_milestone"]].append(self._brief(r))
        return {"groups": [{"category": c, "subcategory": s, "markets": sorted(v, key=lambda x: x["end_ts"] or 0, reverse=True)} for (c, s), v in sorted(groups.items())],
                "clarity_milestones": {k: v for k, v in clarity.items()},
                "milestone_order": [k for k, _ in CLARITY_MILESTONES] + ["other"],
                "official_sources": (self.cfg.official_sources or {}).get("subcategories", {}),
                "note": "Only milestones for which a Polymarket market was actually found are shown. Milestone assignment is a keyword rule on the market question and should be checked against the market's resolution text."}

    def status_view(self, reg: dict, rows: dict) -> dict:
        runs = self.store.load_runs()
        last = runs.get("runs", [])[-20:]
        hist_ts = [r["last_obs_ts"] for r in rows.values() if r["last_obs_ts"]]
        return {"last_success": runs.get("last_success", {}), "recent_runs": last,
                "latest_observation_ts": max(hist_ts) if hist_ts else None,
                "n_markets": len(rows), "n_events": len(reg["events"]),
                "storage": self.store.size_report(),
                "markets_without_history": sum(1 for r in rows.values() if not r["n_history_points"]),
                "categories": {c: sum(1 for r in rows.values() if r["category"] == c) for c in sorted({r["category"] for r in rows.values()})}}

    def summary(self, meta, rows, units, perf, shifts, status) -> dict:
        now = self.now
        active = [r for r in rows.values() if r["status"] == "unresolved" and not r["excluded"] and r["category"] != "crypto_price"]
        upcoming = sorted([r for r in active if (r["end_ts"] or 0) >= now], key=lambda r: r["end_ts"] or 0)[:25]
        awaiting = sorted([r for r in rows.values() if r["status"] in ("unresolved", "proposed", "disputed", "closed_unverified")
                           and (r["end_ts"] or now + 1) < now and not r["excluded"]], key=lambda r: r["end_ts"] or 0, reverse=True)[:25]
        resolved = sorted([r for r in rows.values() if r["status"] == "final" and r["scored_category"] and not r["excluded"]],
                          key=lambda r: r["closed_ts"] or r["end_ts"] or 0, reverse=True)[:25]
        movers = [s for s in shifts["markets"] if s["category"] != "crypto_price"]
        top24 = sorted([s for s in movers if s["d24h"]], key=lambda s: -abs(s["d24h"]["pp_change"]))[:10]
        top7 = sorted([s for s in movers if s["d7d"]], key=lambda s: -abs(s["d7d"]["pp_change"]))[:10]
        return {**meta, "counts": {"markets": len(rows), "active": len(active), "units": len(units),
                                   "scored_primary_events": perf["n_primary_scored_events"]},
                "upcoming": [self._brief(r) for r in upcoming], "awaiting_resolution": [self._brief(r) for r in awaiting],
                "recently_resolved": [self._brief(r) for r in resolved],
                "movers_24h": top24, "movers_7d": top7,
                "headline": {k: perf["by_horizon"][k] for k in perf["horizons"]},
                "by_category_final": {c: v.get("final") for c, v in perf["by_category"].items()},
                "freshness": {"last_success": status["last_success"], "latest_observation_ts": status["latest_observation_ts"]}}

    # ------------------------------------------------------------------ exports
    def exports(self, out_dir, meta, rows, units, perf) -> None:
        hk = [h["key"] for h in self.hz]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["calc_version", "generated_at", "market_id", "event_id", "category", "subcategory", "question", "group_item_title",
                    "tracked_outcome", "status", "resolution_basis", "winner", "outcome_value", "reference_ts_utc", "reference_method",
                    "end_ts_utc", "closed_ts_utc", "quality", "external_verification", "external_source", "duplicate_of", "correlated_with", "flags", "url"]
                   + [f"p_{k}" for k in hk] + [f"obs_ts_{k}" for k in hk] + [f"brier_{k}" for k in hk] + ["retrieved_at_utc"])
        for r in sorted(rows.values(), key=lambda r: r["market_id"]):
            w.writerow([meta["calc_version"], meta["generated_at"], r["market_id"], r["event_id"], r["category"], r["subcategory"],
                        r["question"], r["group_item_title"], r["tracked_outcome"], r["status"], r["resolution_basis"], r["winner"],
                        r["outcome_value"], iso(r["reference_ts"]), r["reference_method"], iso(r["end_ts"]), iso(r["closed_ts"]),
                        r["quality"], (r["external_verification"] or {}).get("status"), r["external_source"], r["duplicate_of"],
                        r["correlated_with"], ";".join(r["flags"]), r["url"]]
                       + [r["forecasts"].get(k, {}).get("p") for k in hk]
                       + [iso(r["forecasts"].get(k, {}).get("obs_ts")) for k in hk]
                       + [r["brier"].get(k) for k in hk] + [iso(r["retrieved_at"])])
        atomic_write(out_dir / "exports" / "market_forecasts.csv", buf.getvalue())

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["calc_version", "unit_id", "event_id", "type", "category", "subcategory", "status", "primary", "correlated_with",
                    "exclusion_reason", "reference_ts_utc", "quality", "K"] + [f"score_{k}" for k in hk] + [f"uniform_{k}" for k in hk] + [f"base_rate_{k}" for k in hk])
        for u in units:
            w.writerow([meta["calc_version"], u["unit_id"], u["event_id"], u["type"], u["category"], u["subcategory"], u["status"],
                        u["primary"], u["correlated_with"], u["exclusion_reason"], iso(u.get("reference_ts")), u.get("quality"), u.get("K")]
                       + [u["scores"].get(k) for k in hk] + [u.get("baseline_uniform", {}).get(k) for k in hk]
                       + [u.get("baseline_base_rate", {}).get(k) for k in hk])
        atomic_write(out_dir / "exports" / "event_scores.csv", buf.getvalue())
        write_json(out_dir / "exports" / "accuracy_metrics.json", {**meta, "settings": self.s, **perf})
