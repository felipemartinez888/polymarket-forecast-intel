"""FOMC meeting alignment and external verification against official Fed decisions."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
INF = math.inf


def announcement_ts(meeting: dict, fomc_doc: dict) -> int:
    hh, mm = (int(x) for x in fomc_doc.get("announcement_local_time", "14:00").split(":"))
    tz = ZoneInfo(fomc_doc.get("announcement_tz", "America/New_York"))
    y, m, d = (int(x) for x in meeting["announcement_date"].split("-"))
    return int(datetime(y, m, d, hh, mm, tzinfo=tz).timestamp())


def match_meeting(event_title: str, event_end_ts: int | None, fomc_doc: dict) -> dict | None:
    """Match a Polymarket Fed-decision event to an official meeting.

    1) month named in the title (+ explicit year, else year of the event end date);
    2) fallback: the meeting whose announcement is within 7 days of the event end date.
    Returns None when no unambiguous match exists.
    """
    meetings = fomc_doc["meetings"]
    t = (event_title or "").lower()
    yr_m = re.search(r"\b(20\d\d)\b", t)
    end_year = datetime.fromtimestamp(event_end_ts, timezone.utc).year if event_end_ts else None
    year = int(yr_m.group(1)) if yr_m else end_year
    named = [i + 1 for i, mo in enumerate(MONTHS) if re.search(rf"\b{mo}\b", t)]
    if len(named) == 1 and year:
        mo = named[0]
        hits = [m for m in meetings if m["announcement_date"].startswith(f"{year}-{mo:02d}")]
        if len(hits) == 1:
            return hits[0]
        # April/May joint meeting naming ("May" meeting announced on May 1 or April 30)
        if not hits:
            adj = [m for m in meetings if abs((int(m["announcement_date"][:4]) * 12 + int(m["announcement_date"][5:7])) - (year * 12 + mo)) == 1]
            if end_year and event_end_ts:
                adj = [m for m in adj if abs(announcement_ts(m, fomc_doc) - event_end_ts) < 10 * 86400]
            if len(adj) == 1:
                return adj[0]
    if event_end_ts:
        near = [m for m in meetings if abs(announcement_ts(m, fomc_doc) - event_end_ts) <= 7 * 86400]
        if len(near) == 1:
            return near[0]
    return None


def parse_decision_range(text: str) -> tuple[float, float] | None:
    """Map an outcome label/question to the inclusive bps range it pays out on.

    Examples: 'No change' -> (0,0); '25 bps decrease' -> (-25,-25);
    '50+ bps decrease' -> (-inf,-50); '25+ bps increase' -> (25, inf); 'Fed cuts rates?' -> (-inf,-1).
    Returns None if the label cannot be mapped unambiguously.
    """
    t = (text or "").lower()
    if re.search(r"\b(no change|unchanged|hold|holds|pause|pauses|maintain|steady)\b", t):
        return (0.0, 0.0)
    down = re.search(r"\b(decrease|decreases|cut|cuts|lower|lowers|reduce|reduces|reduction)\b", t)
    up = re.search(r"\b(increase|increases|hike|hikes|raise|raises|higher)\b", t)
    if bool(down) == bool(up):
        return None
    sign = -1 if down else 1
    nums = re.findall(r"(\d+)\s*(\+)?\s*(?:bps|bp|basis points)", t)
    if len(nums) > 1:
        return None
    if not nums:
        return (-INF, -1.0) if sign < 0 else (1.0, INF)
    n, plus = float(nums[0][0]), bool(nums[0][1]) or bool(re.search(r"\bor more\b", t))
    if sign < 0:
        return (-INF, -n) if plus else (-n, -n)
    return (n, INF) if plus else (n, n)


def expected_yes(label_text: str, decision_bps: float) -> bool | None:
    rng = parse_decision_range(label_text)
    if rng is None:
        return None
    return rng[0] <= decision_bps <= rng[1]


def verify_fed_market(market: dict, meeting: dict | None) -> dict:
    """Cross-check a resolved Fed-decision market against the official decision."""
    out = {"status": "not_applicable", "source": None, "expected_yes": None, "detail": None}
    if meeting is None:
        out.update(status="unmatched_meeting")
        return out
    if meeting.get("decision_bps") is None:
        out.update(status="official_decision_pending")
        return out
    label = market.get("group_item_title") or market.get("question") or ""
    exp = expected_yes(label, meeting["decision_bps"])
    if exp is None:
        exp = expected_yes(market.get("question") or "", meeting["decision_bps"])
    out["source"] = meeting.get("statement_url")
    if exp is None:
        out.update(status="unmapped_outcome_label", detail=label)
        return out
    out["expected_yes"] = exp
    res = market["resolution"]
    if res["status"] != "final":
        out.update(status="awaiting_polymarket_resolution")
        return out
    yes_won = res["winner_index"] == market["track_index"] and str(market.get("track_label", "")).lower() == "yes"
    if str(market.get("track_label", "")).lower() != "yes":
        out.update(status="unmapped_outcome_label", detail="market is not Yes/No")
        return out
    out["status"] = "verified" if yes_won == exp else "conflict"
    out["detail"] = f"official {meeting['decision_bps']:+d} bps; Polymarket {'YES' if yes_won else 'NO'}"
    return out
