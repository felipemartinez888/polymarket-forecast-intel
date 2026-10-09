import math

import pytest

from pipeline.classify import Classifier, find_duplicates, normalize_question
from pipeline.config import load_config
from pipeline.fomc import announcement_ts, expected_yes, match_meeting, parse_decision_range, verify_fed_market
from pipeline.parse import parse_market, parse_ts
from pipeline.timing import forecast_at, reference_time, settlement_onset, value_at_or_before
from tests.fixtures.fake_api import mk

CFG = load_config()


def cls(title, q="", group=None, overrides=None):
    c = Classifier(CFG.rules, overrides or {"markets": {}, "events": {}})
    return c.classify(title, {"question": q, "group_item_title": group, "market_id": "1", "event_id": "2"})


@pytest.mark.parametrize("title,q,cat,sub", [
    ("Fed decision in September?", "Will the Fed decrease interest rates by 25 bps?", "fed", "fomc_decision"),
    ("How many Fed rate cuts in 2026?", "3 cuts?", "fed", "rate_path"),
    ("Who will Trump nominate as Fed Chair?", "Kevin Hassett?", "fed", "leadership"),
    ("Clarity Act signed into law in 2026?", "", "crypto_regulation", "clarity_act"),
    ("Digital Asset Market Clarity Act passes Senate?", "", "crypto_regulation", "clarity_act"),
    ("Stablecoin bill passes Senate?", "", "crypto_regulation", "stablecoin"),
    ("SEC approves Solana ETF in 2025?", "", "crypto_events", "etf_decision"),
    ("SEC drops lawsuit against Ripple?", "", "crypto_regulation", "agency_action"),
    ("Bitcoin above $150k on Dec 31?", "", "crypto_price", "price_direction"),
    ("Ethereum up or down today?", "", "crypto_price", "price_direction"),
    ("US recession in 2026?", "", "macro", "recession"),
    ("September CPI above 3.0%?", "", "macro", "cpi"),
    ("Core CPI MoM in August?", "", "macro", "core_cpi"),
    ("Jobs report: nonfarm payrolls above 100k?", "", "macro", "nonfarm_payrolls"),
    ("US Q3 GDP growth above 2%?", "", "macro", "gdp"),
])
def test_rules(title, q, cat, sub):
    r = cls(title, q)
    assert (r["category"], r["subcategory"]) == (cat, sub), r
    assert r["rule_id"]


@pytest.mark.parametrize("title", ["FedEx earnings beat?", "Will Messi score?", "UK inflation above 3%?", "Who wins the Super Bowl?"])
def test_rules_negative(title):
    assert cls(title)["category"] is None


def test_override_wins_and_is_audited():
    r = cls("US recession in 2026?", overrides={"markets": {"1": {"relevance": "high", "exclude": True, "note": "x"}}, "events": {}})
    assert r["relevance"] == "high" and r["excluded"] and r["override"]["note"] == "x"


def test_duplicate_detection():
    a = parse_market(mk(10, "Will the Clarity Act be signed into law in 2025?", end="2025-12-31T00:00:00Z", volume=5))
    b = parse_market(mk(11, "Clarity Act signed into law in 2025", end="2025-12-31T00:00:00Z", volume=50))
    c = parse_market(mk(12, "Clarity Act signed into law in 2025", end="2026-12-31T00:00:00Z", volume=50))
    assert normalize_question(a["question"]) == normalize_question(b["question"])
    assert find_duplicates([a, b, c]) == {"10": "11"}


@pytest.mark.parametrize("label,rng", [
    ("No change", (0, 0)), ("25 bps decrease", (-25, -25)), ("50+ bps decrease", (-math.inf, -50)),
    ("25+ bps increase", (25, math.inf)), ("Fed cuts rates in March?", (-math.inf, -1)),
    ("Decrease rates by 50 bps or more", (-math.inf, -50)), ("weird label", None), ("cut or hike", None),
])
def test_decision_ranges(label, rng):
    assert parse_decision_range(label) == rng


def test_expected_yes():
    assert expected_yes("25 bps decrease", -25) is True
    assert expected_yes("50+ bps decrease", -25) is False
    assert expected_yes("No change", 0) is True
    assert expected_yes("25+ bps increase", 25) is True


def test_meeting_match_and_announcement_time():
    m = match_meeting("Fed decision in September?", parse_ts("2025-09-17T18:00:00Z"), CFG.fomc)
    assert m["id"] == "2025-09"
    assert announcement_ts(m, CFG.fomc) == parse_ts("2025-09-17T18:00:00Z")            # 14:00 EDT
    jan = next(x for x in CFG.fomc["meetings"] if x["id"] == "2025-01")
    assert announcement_ts(jan, CFG.fomc) == parse_ts("2025-01-29T19:00:00Z")          # 14:00 EST
    assert match_meeting("Fed decision in May?", parse_ts("2024-05-01T18:00:00Z"), CFG.fomc)["id"] == "2024-05"
    assert match_meeting("Fed decision in August?", parse_ts("2025-08-20T18:00:00Z"), CFG.fomc) is None


def test_fed_verification_verified_and_conflict():
    mt = next(x for x in CFG.fomc["meetings"] if x["id"] == "2025-09")
    win = parse_market(mk(1, "Q", group="25 bps decrease", closed=True, uma="resolved", prices=[1, 0]))
    assert verify_fed_market(win, mt)["status"] == "verified"
    bad = parse_market(mk(2, "Q", group="No change", closed=True, uma="resolved", prices=[1, 0]))
    assert verify_fed_market(bad, mt)["status"] == "conflict"
    pend = next(x for x in CFG.fomc["meetings"] if x["decision_bps"] is None)
    assert verify_fed_market(win, pend)["status"] == "official_decision_pending"


# ---------------- timing / look-ahead ----------------
PTS = [[100, 0.2], [200, 0.3], [300, 0.9], [400, 1.0]]


def test_forecast_never_uses_reference_or_later():
    f = forecast_at(PTS, 300, 0, 1000, buffer_s=0)
    assert f["status"] == "ok" and f["obs_ts"] == 200 and f["p"] == 0.3
    f = forecast_at(PTS, 301, 0, 1000, buffer_s=60)
    assert f["obs_ts"] == 200  # 300 is within the 60s pre-announcement buffer


def test_forecast_horizon_and_staleness():
    assert forecast_at(PTS, 400, 150, 1000)["obs_ts"] == 200
    assert forecast_at(PTS, 400, 350, 1000)["reason"] == "market_not_yet_trading"
    f = forecast_at([[0, 0.5]], 10000, 0, 100)
    assert f["status"] == "missing" and f["reason"] == "stale_observation"
    assert forecast_at([], 10, 0, 100)["reason"] == "no_price_history"


def test_settlement_onset_and_reference_methods():
    pts = [[1, 0.5], [2, 0.6], [3, 0.97], [4, 0.99], [5, 1.0]]
    assert settlement_onset(pts, 1, 0.05, None) == 3
    assert settlement_onset(pts, 1, 0.05, 2) is None
    yes = {"end_ts": 100, "closed_ts": 120, "track_index": 0, "resolution": {"status": "final", "winner_index": 0}}
    assert reference_time(yes, "deadline", None, pts, 0.05) == (3, "settlement_onset")
    no = {**yes, "resolution": {"status": "final", "winner_index": 1}}
    assert reference_time(no, "deadline", None, pts, 0.05) == (100, "end_date")
    assert reference_time(yes, "scheduled_announcement", 50, pts, 0.05) == (50, "scheduled_announcement")
    assert reference_time(yes, "deadline", None, pts, 0.05, override_ts=42) == (42, "override")


def test_value_at_or_before_tolerance():
    assert value_at_or_before(PTS, 250, 100) == (200, 0.3)
    assert value_at_or_before(PTS, 250, 10) is None
    assert value_at_or_before(PTS, 50, 1000) is None
