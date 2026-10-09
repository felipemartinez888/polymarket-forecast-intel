"""Full pipeline on the SYNTHETIC fixture API: discover -> resolve -> analyze."""
import json
import urllib.error

import pytest

from pipeline import http as H
from pipeline.analyze import Analyzer
from pipeline.collect import Collector
from pipeline.config import load_config
from pipeline.store import Store
from tests.fixtures.fake_api import FakeClient, ts


@pytest.fixture()
def run(tmp_path):
    cfg = load_config(tmp_path)
    cfg.settings["discovery"]["search_queries"] = ["fed", "clarity", "bitcoin", "stablecoin", "recession"]
    cfg.settings["discovery"]["tag_slugs"] = ["fed"]
    fake = FakeClient()
    store = Store(tmp_path)
    col = Collector(cfg, client=fake, store=store, now=lambda: fake.now)
    d = col.run_discover()
    r = col.run_resolve()
    a = Analyzer(cfg, store, now=fake.now).run()
    out = {n: json.loads((tmp_path / "derived" / f"{n}.json").read_text()) for n in
           ("markets", "units", "performance", "shifts", "fed", "regulation", "summary", "status")}
    return {"cfg": cfg, "store": store, "col": col, "fake": fake, "d": d, "r": r, "a": a, **out}


def by_id(rows, key="market_id"):
    return {r[key]: r for r in rows}


def test_discovery_and_classification(run):
    m = by_id(run["markets"]["markets"])
    assert set(m) == {"101", "102", "103", "104", "201", "301", "401", "501", "601", "701", "702", "703", "801", "901"}
    assert m["501"]["category"] == "crypto_price" and not m["501"]["scored_category"]
    assert m["101"]["rule_id"] == "fed_decision"


def test_fed_multiclass_unit_scored_without_lookahead(run):
    u = by_id(run["units"]["units"], "unit_id")["E9001"]
    assert u["type"] == "multiclass" and u["status"] == "final" and u["primary"]
    assert u["reference_ts"] == ts("2025-09-17T18:00:00Z")
    f = u["forecasts"]["final"]
    assert f["normalized"] == pytest.approx([0.15, 0.80, 0.04, 0.01])
    assert all(t < u["reference_ts"] for t in f["obs_ts"])  # post-announcement point excluded
    assert u["scores"]["final"] == pytest.approx(0.0642)
    assert u["baseline_uniform"]["final"] == pytest.approx(0.75)
    assert u["quality"] == "A"  # externally verified against federalreserve.gov


def test_fed_external_verification(run):
    m = by_id(run["markets"]["markets"])
    assert m["102"]["external_verification"]["status"] == "verified"
    assert m["101"]["external_verification"]["status"] == "verified"  # NO on 'No change' matches official -25
    assert m["102"]["external_source"].startswith("https://www.federalreserve.gov/")


def test_correlated_fed_market_not_double_counted(run):
    u = by_id(run["units"]["units"], "unit_id")["E9002"]
    assert u["primary"] is False and u["correlated_with"] == "E9001"
    fed_final = run["fed"]["brier_by_lead_time"]["final"]
    assert fed_final["n_events"] == 1


def test_duplicate_excluded(run):
    m = by_id(run["markets"]["markets"])
    assert m["601"]["duplicate_of"] == "301" and "duplicate" in m["601"]["flags"]
    assert "E9006" not in by_id(run["units"]["units"], "unit_id")


def test_deadline_yes_uses_settlement_onset(run):
    m = by_id(run["markets"]["markets"])["801"]
    assert m["reference_method"] == "settlement_onset"
    assert m["reference_ts"] == ts("2025-07-18T20:00:00Z")
    assert m["forecasts"]["final"]["p"] == 0.6
    assert m["brier"]["final"] == pytest.approx(0.16)


def test_invalid_market_not_scored(run):
    u = by_id(run["units"]["units"], "unit_id")["E9009"]
    assert u["status"] == "not_scoreable" and not u["scores"]


def test_crypto_price_never_in_units(run):
    assert all(u["category"] != "crypto_price" for u in run["units"]["units"])


def test_performance_aggregates(run):
    p = run["performance"]
    # primary final units: E9001 (multiclass), E9003 (clarity NO), E9008 (stablecoin YES)
    assert p["n_primary_scored_events"] == 3
    fin = p["by_horizon"]["final"]
    assert fin["multiclass"]["n_events"] == 1 and fin["binary_set"]["n_events"] == 2
    assert fin["binary_set"]["mean_brier"] == pytest.approx((0.01 + 0.16) / 2)
    assert sum(b["n"] for b in p["calibration"]["final"]["bins"]) == 4 + 2  # 4 fed outcomes + 2 binaries


def test_base_rate_baseline_has_no_lookahead(run):
    # E9008 (Jul 2025) is the first resolved stablecoin market -> base rate = Laplace prior 0.5
    u = by_id(run["units"]["units"], "unit_id")["E9008"]
    assert u["baseline_base_rate"]["final"] == pytest.approx(0.25)


def test_shift_monitor(run):
    s = by_id(run["shifts"]["markets"])["401"]
    assert s["d24h"]["pp_change"] == pytest.approx(22.0)
    assert s["d24h"]["relative_change_pct"] == pytest.approx(55.0)
    assert s["d7d"]["pp_change"] == pytest.approx(27.0)
    assert s["flag_24h"] and s["flag_7d"]


def test_upcoming_meeting_and_future_horizons(run):
    fed = run["fed"]
    assert fed["upcoming_meeting_id"] == "2026-10"
    up = next(m for m in fed["meetings"] if m["id"] == "2026-10")
    outs = up["events"][0]["outcomes"]
    assert {o["label"] for o in outs} == {"No change", "25 bps increase", "25 bps decrease"}
    assert outs[0]["missing"]["14d"] == "future"
    assert outs[0]["verification"]["status"] == "official_decision_pending"


def test_freeze_and_snapshots(run):
    reg = run["store"].load_registry()
    assert reg["events"]["9001"]["frozen"] and not reg["events"]["9004"].get("frozen")
    snaps = list(run["store"].iter_snapshots())
    assert {s["market_id"] for s in snaps} == {"401", "701", "702", "703"}


def test_regulation_view_only_real_milestones(run):
    ms = run["regulation"]["clarity_milestones"]
    assert set(ms) == {"presidential_signature", "senate_passage"}


def test_exports_have_provenance(run, tmp_path):
    csv_text = (tmp_path / "derived" / "exports" / "market_forecasts.csv").read_text()
    header = csv_text.splitlines()[0]
    for col in ("calc_version", "market_id", "event_id", "obs_ts_final", "reference_method", "url", "retrieved_at_utc"):
        assert col in header


def test_api_failure_marks_incomplete_and_keeps_data(tmp_path):
    cfg = load_config(tmp_path)
    cfg.settings["discovery"]["search_queries"] = ["clarity"]
    cfg.settings["discovery"]["tag_slugs"] = []
    fake = FakeClient()
    fake.fail_tokens = {"tok301y"}
    store = Store(tmp_path)
    col = Collector(cfg, client=fake, store=store, now=lambda: fake.now)
    col.run_discover()
    col.run_resolve()
    assert any(i["market_id"] == "301" and i["reason"] == "history_fetch_failed" for i in col.incomplete)
    assert not store.load_registry()["events"]["9003"].get("frozen")
    Analyzer(cfg, store, now=fake.now).run()
    m = by_id(json.loads((tmp_path / "derived" / "markets.json").read_text())["markets"])["301"]
    assert m["forecasts"]["final"]["reason"] == "no_price_history" and "301" not in [k for k in m["brier"]]


def test_snapshot_and_history_dedup(tmp_path):
    s = Store(tmp_path)
    row = {"t": 7200, "market_id": "1", "p": 0.5}
    assert s.append_snapshots([row, {**row, "t": 7300}], "2026-10") == 1  # same hour bucket
    assert s.append_snapshots([row], "2026-10") == 0
    s.merge_history("1", "tok", "Yes", [[1, 0.1], [2, 0.2]], 10, 60, 100)
    h = s.merge_history("1", "tok", "Yes", [[2, 0.25], [3, 0.3]], 20, 60, 100)
    assert h["points"] == [[1, 0.1], [2, 0.25], [3, 0.3]]
    with pytest.raises(ValueError):
        s.merge_history("1", "other", "Yes", [], 30, 60, 100)


def test_http_retry_backoff(monkeypatch):
    calls = {"n": 0}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok": true}'

    def fake_urlopen(req, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(req.full_url, 503, "busy", None, None)
        return Resp()

    monkeypatch.setattr(H.urllib.request, "urlopen", fake_urlopen)
    slept = []
    c = H.Client(load_config().settings, sleep=slept.append)
    assert c.get_json("https://x", "/y", {"a": 1, "b": None}) == {"ok": True}
    assert calls["n"] == 3 and len(slept) >= 2

    def always_404(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", None, None)
    monkeypatch.setattr(H.urllib.request, "urlopen", always_404)
    with pytest.raises(H.HttpError):
        c.get_json("https://x", "/y")


def test_time_budget_defers_history_without_losing_metadata(tmp_path):
    cfg = load_config(tmp_path)
    cfg.settings["discovery"]["search_queries"] = ["clarity"]
    cfg.settings["discovery"]["tag_slugs"] = []
    cfg.settings["history"]["run_budget_seconds"] = -1  # already over budget
    fake = FakeClient()
    store = Store(tmp_path)
    col = Collector(cfg, client=fake, store=store, now=lambda: fake.now)
    col.run_discover()
    col.run_resolve()
    reg = store.load_registry()
    assert "301" in reg["markets"] and not reg["events"]["9003"].get("frozen")
    assert store.load_history("301") is None
    assert any(i["reason"] == "deferred_time_budget" for i in col.incomplete)


def test_long_windows_are_halved_and_full_history_recovered(tmp_path):
    cfg = load_config(tmp_path)
    cfg.settings["discovery"]["search_queries"] = ["fed"]
    cfg.settings["discovery"]["tag_slugs"] = []
    cfg.settings["history"]["chunk_days"] = 60  # deliberately too long for the (fake) CLOB
    fake = FakeClient()
    store = Store(tmp_path)
    col = Collector(cfg, client=fake, store=store, now=lambda: fake.now)
    col.run_discover()
    col.run_resolve()
    h = store.load_history("102")
    assert h["complete"] and h["first_ts"] <= ts("2025-07-16T00:00:00Z")  # not just the last week
    assert not [e for e in col.errors if "too long" in e["error"]]


def test_backfill_prioritizes_fed_and_resumes(tmp_path):
    cfg = load_config(tmp_path)
    cfg.settings["discovery"]["search_queries"] = ["fed", "clarity", "stablecoin"]
    cfg.settings["discovery"]["tag_slugs"] = []
    fake = FakeClient()
    store = Store(tmp_path)
    Collector(cfg, client=fake, store=store, now=lambda: fake.now).run_discover()  # registry only for closed events
    col = Collector(cfg, client=fake, store=store, now=lambda: fake.now)
    res = col.run_backfill(limit=4)
    assert res["histories_backfilled"] == 4 and res["remaining"] > 0
    got = {mid for mid in ("101", "102", "103", "104") if (store.load_history(mid) or {}).get("complete")}
    assert got == {"101", "102", "103", "104"}  # FOMC decision markets first
    res2 = Collector(cfg, client=fake, store=store, now=lambda: fake.now).run_backfill()
    assert res2["remaining"] == 0
