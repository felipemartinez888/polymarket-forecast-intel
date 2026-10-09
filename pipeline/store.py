"""File-based persistent storage (the `data` git branch).

Layout:
  data/registry.json               events + markets metadata (latest), with first_seen/last_seen
  data/history/<market_id>.json    CLOB price history for the tracked outcome token, merged & de-duplicated
  data/snapshots/YYYY-MM.jsonl     append-only Gamma price snapshots, de-duplicated by (market_id, hour)
  data/runs.json                   bounded run log (status, counts, errors, incomplete windows)
  data/derived/*.json|csv          analytics consumed by the dashboard (regenerable)
All writes are atomic (write temp file + rename).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SCHEMA_VERSION = 1


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_json(path: Path, obj, compact: bool = False) -> None:
    text = json.dumps(obj, separators=(",", ":") if compact else None, indent=None if compact else 1,
                      sort_keys=not compact, default=str)
    atomic_write(path, text + "\n")


def read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- registry ----
    @property
    def registry_path(self) -> Path:
        return self.root / "registry.json"

    def load_registry(self) -> dict:
        reg = read_json(self.registry_path) or {}
        reg.setdefault("schema_version", SCHEMA_VERSION)
        reg.setdefault("events", {})
        reg.setdefault("markets", {})
        return reg

    def save_registry(self, reg: dict) -> None:
        write_json(self.registry_path, reg)

    # ---- price history ----
    def history_path(self, market_id: str) -> Path:
        return self.root / "history" / f"{market_id}.json"

    def load_history(self, market_id: str) -> dict | None:
        return read_json(self.history_path(market_id))

    def merge_history(self, market_id: str, token_id: str, outcome_label: str, new_points: list[list],
                      retrieved_at: int, fidelity: int, max_points: int, complete: bool = False) -> dict:
        cur = self.load_history(market_id) or {
            "market_id": market_id, "token_id": token_id, "outcome": outcome_label,
            "source": "clob.polymarket.com/prices-history", "fidelity_minutes": fidelity, "points": [],
        }
        if cur.get("token_id") and cur["token_id"] != token_id:
            raise ValueError(f"token mismatch for market {market_id}")
        merged = {int(t): p for t, p in cur["points"]}
        for t, p in new_points:
            merged[int(t)] = p  # identical timestamps: newest retrieval wins (same source)
        pts = [[t, merged[t]] for t in sorted(merged)]
        if len(pts) > max_points:
            pts = pts[-max_points:]
            cur["truncated"] = True
        cur.update(points=pts, retrieved_at=retrieved_at, n_points=len(pts), complete=complete,
                   first_ts=pts[0][0] if pts else None, last_ts=pts[-1][0] if pts else None)
        write_json(self.history_path(market_id), cur, compact=True)
        return cur

    # ---- snapshots ----
    def append_snapshots(self, rows: list[dict], month: str) -> int:
        """Append rows, skipping any (market_id, hour_bucket) already present. Returns rows written."""
        path = self.root / "snapshots" / f"{month}.jsonl"
        seen = set()
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                        seen.add((r["market_id"], r["t"] // 3600))
                    except (json.JSONDecodeError, KeyError):
                        continue
        new = []
        for r in rows:
            key = (r["market_id"], r["t"] // 3600)
            if key not in seen:
                seen.add(key)
                new.append(r)
        if new:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                for r in new:
                    fh.write(json.dumps(r, separators=(",", ":")) + "\n")
        return len(new)

    def iter_snapshots(self):
        d = self.root / "snapshots"
        if not d.exists():
            return
        for p in sorted(d.glob("*.jsonl")):
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    # ---- run log ----
    def log_run(self, run: dict, max_runs: int) -> None:
        path = self.root / "runs.json"
        runs = read_json(path, {"runs": []})
        runs["runs"].append(run)
        runs["runs"] = runs["runs"][-max_runs:]
        if run.get("status") in ("ok", "partial"):
            runs.setdefault("last_success", {})[run["command"]] = run["finished_at"]
        write_json(path, runs)

    def load_runs(self) -> dict:
        return read_json(self.root / "runs.json", {"runs": []})

    def derived(self, name: str) -> Path:
        return self.root / "derived" / name

    def size_report(self) -> dict:
        total, files = 0, 0
        for p in self.root.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
                files += 1
        return {"bytes": total, "files": files}
