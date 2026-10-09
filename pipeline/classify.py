"""Auditable rule-based classification, relevance tagging and duplicate detection."""
from __future__ import annotations

import re
import unicodedata

CATEGORIES = ["fed", "crypto_regulation", "macro", "crypto_events", "crypto_price"]
# crypto_price is collected for context but excluded from headline accuracy aggregates.
SCORED_CATEGORIES = {"fed", "crypto_regulation", "macro", "crypto_events"}


class Classifier:
    def __init__(self, rules_doc: dict, overrides: dict):
        self.version = rules_doc.get("version", "0")
        self.rules = []
        for r in rules_doc["rules"]:
            self.rules.append({
                **r,
                "_any": [re.compile(p, re.I) for p in r.get("any", [])],
                "_all": [re.compile(p, re.I) for p in r.get("all", [])],
                "_none": [re.compile(p, re.I) for p in r.get("none", [])],
            })
        self.mo = overrides.get("markets", {}) or {}
        self.eo = overrides.get("events", {}) or {}

    @staticmethod
    def text(event_title: str, market: dict) -> str:
        return " || ".join(x for x in [event_title or "", market.get("question") or "", market.get("group_item_title") or ""] if x).lower()

    def classify(self, event_title: str, market: dict) -> dict:
        txt = self.text(event_title, market)
        result = {"category": None, "subcategory": None, "relevance": None, "rule_id": None,
                  "rules_version": self.version, "override": None, "excluded": False}
        for r in self.rules:
            if not any(p.search(txt) for p in r["_any"]):
                continue
            if not all(p.search(txt) for p in r["_all"]):
                continue
            if any(p.search(txt) for p in r["_none"]):
                continue
            result.update(category=r["category"], subcategory=r["subcategory"],
                          relevance=r["relevance"], rule_id=r["id"])
            break
        ov = {**self.eo.get(str(market.get("event_id")), {}), **self.mo.get(str(market.get("market_id")), {})}
        if ov:
            for k in ("category", "subcategory", "relevance"):
                if ov.get(k):
                    result[k] = ov[k]
            if ov.get("exclude"):
                result["excluded"] = True
            result["override"] = {k: v for k, v in ov.items()}
        return result


_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"


def normalize_question(q: str) -> str:
    s = unicodedata.normalize("NFKD", q or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[?!.,'\"()\[\]:;]", " ", s)
    s = re.sub(r"\b(will|the|a|an|by|in|on|of|be)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def duplicate_key(market: dict) -> str:
    """Two markets with the same normalized question and the same end date (UTC day) are treated as duplicates."""
    from .parse import iso
    day = (iso(market.get("end_ts")) or "")[:10]
    return f"{normalize_question(market.get('question', ''))}|{day}"


def find_duplicates(markets: list[dict]) -> dict[str, str]:
    """Return {duplicate_market_id: canonical_market_id}. Canonical = highest volume, then lowest id."""
    groups: dict[str, list[dict]] = {}
    for m in markets:
        groups.setdefault(duplicate_key(m), []).append(m)
    dup = {}
    for g in groups.values():
        if len(g) < 2:
            continue
        g.sort(key=lambda m: (-(m.get("volume") or 0), int(m["market_id"]) if str(m["market_id"]).isdigit() else 0))
        for m in g[1:]:
            dup[m["market_id"]] = g[0]["market_id"]
    return dup
