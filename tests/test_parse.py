import json

import pytest

from pipeline.parse import ParseError, parse_event, parse_market, parse_price_history, parse_ts, resolution_from_market
from tests.fixtures.fake_api import build, mk


def test_json_string_fields_decoded():
    m = parse_market(mk(1, "Q?", yes_price=0.3))
    assert m["outcomes"] == ["Yes", "No"]
    assert m["outcome_prices"] == [0.3, 0.7]
    assert m["token_ids"] == ["tok1y", "tok1n"]
    assert m["track_index"] == 0 and m["track_token"] == "tok1y"


def test_non_yes_no_market_tracks_first_outcome():
    m = parse_market(mk(2, "Up or down?", outcomes=("Up", "Down"), prices=[0.4, 0.6]))
    assert m["track_label"] == "Up" and m["track_index"] == 0


def test_yes_not_first_index():
    raw = mk(3, "Q?", outcomes=("No", "Yes"), prices=[0.2, 0.8])
    m = parse_market(raw)
    assert m["track_index"] == 1 and m["track_token"] == "tok3n"


@pytest.mark.parametrize("kw,status,basis,winner", [
    (dict(yes_price=0.4), "unresolved", None, None),
    (dict(yes_price=0.4, uma="proposed"), "proposed", "uma_status", None),
    (dict(closed=True, uma="disputed", prices=[1, 0]), "disputed", "uma_status", None),
    (dict(closed=True, uma="resolved", prices=[1, 0]), "final", "uma_resolved", "Yes"),
    (dict(closed=True, uma="resolved", prices=[0, 1]), "final", "uma_resolved", "No"),
    (dict(closed=True, uma=None, prices=[0, 1]), "final", "settlement_prices_only", "No"),
    (dict(closed=True, uma="resolved", prices=[0.5, 0.5]), "invalid", "equal_split_settlement", None),
    (dict(closed=True, uma=None, prices=[0.62, 0.38]), "closed_unverified", "closed_without_one_hot_settlement", None),
])
def test_resolution_states(kw, status, basis, winner):
    r = resolution_from_market(mk(5, "Q?", **kw))
    assert r["status"] == status and r["basis"] == basis and r["winner_label"] == winner


def test_resolution_never_inferred_from_end_date():
    raw = mk(6, "Q?", yes_price=0.97, end="2020-01-01T00:00:00Z")  # long past end date, still open
    assert resolution_from_market(raw)["status"] == "unresolved"


def test_disputed_history_is_recorded():
    r = resolution_from_market(mk(7, "Q?", closed=True, uma="resolved", uma_hist=["proposed", "disputed", "resolved"], prices=[1, 0]))
    assert r["status"] == "final" and r["was_disputed"]


def test_malformed_prices():
    raw = mk(8, "Q?", closed=True, uma="resolved")
    raw["outcomePrices"] = "not json"
    m = parse_market(raw)
    assert m["resolution"]["status"] == "closed_unverified"
    assert any("outcomePrices" in e for e in m["parse_errors"])


def test_market_without_id_rejected():
    with pytest.raises(ParseError):
        parse_market({"question": "x"})


def test_parse_event():
    events, _, _ = build()
    ev, ms = parse_event(events["9001"])
    assert ev["neg_risk"] and len(ms) == 4 and ev["event_id"] == "9001"
    assert ev["url"] == "https://polymarket.com/event/e-9001"
    assert ms[0]["event_id"] == "9001"


def test_price_history_parse_sorts_dedupes_validates():
    pts = parse_price_history({"history": [{"t": 3, "p": 0.3}, {"t": 1, "p": 0.1}, {"t": 3, "p": 0.31},
                                           {"t": 4, "p": 1.7}, {"t": "x", "p": 0.2}, {"t": 5, "p": "0.5"}]})
    assert pts == [[1, 0.1], [3, 0.31], [5, 0.5]]
    with pytest.raises(ParseError):
        parse_price_history({"error": "bad"})


def test_parse_ts_formats():
    assert parse_ts("2025-09-17T18:00:00Z") == 1758132000
    assert parse_ts("2025-09-17 18:00:00+00") == 1758132000
    assert parse_ts("2025-09-17") == 1758067200
    assert parse_ts(1758132000000) == 1758132000
    assert parse_ts(None) is None and parse_ts("garbage") is None
