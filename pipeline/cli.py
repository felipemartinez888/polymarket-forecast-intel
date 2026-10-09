"""Command-line entry point.

  python -m pipeline.cli discover      # find markets, refresh active ones, snapshots + incremental history
  python -m pipeline.cli resolve       # verify resolutions, fetch final histories, freeze finished events
  python -m pipeline.cli backfill [N]  # full history for tracked markets that have none (optionally first N)
  python -m pipeline.cli analyze       # recompute all derived analytics (no network)
  python -m pipeline.cli all           # discover + resolve + analyze
  python -m pipeline.cli check         # validate stored data integrity (no network)

Exit code is 0 on success or partial success (some API calls failed but valid data was kept),
1 only if a command failed outright. Every run is appended to data/runs.json.
"""
from __future__ import annotations

import sys
import time
import traceback

from . import log
from .analyze import Analyzer
from .collect import Collector
from .config import load_config
from .parse import iso
from .store import Store


def _run(cmd: str, fn, store: Store, cfg, collector: Collector | None = None) -> bool:
    started = int(time.time())
    rec = {"command": cmd, "started_at": iso(started), "calc_version": cfg.calc_version}
    ok = True
    try:
        result = fn()
        rec["result"] = result
        errs = collector.errors if collector else []
        rec["status"] = "partial" if errs else "ok"
        if collector:
            rec["errors"] = errs[:50]
            rec["n_errors"] = len(errs)
            rec["incomplete"] = collector.incomplete[:200]
            rec["http_requests"] = collector.client.requests
    except Exception as e:  # noqa: BLE001 — record & surface any failure
        ok = False
        rec["status"] = "failed"
        rec["error"] = repr(e)
        rec["traceback"] = traceback.format_exc()[-2000:]
        log.error("command_failed", command=cmd, error=repr(e))
    rec["finished_at"] = iso(int(time.time()))
    rec["duration_s"] = int(time.time()) - started
    store.log_run(rec, cfg.settings["storage"]["max_runs_logged"])
    log.info("command_done", command=cmd, status=rec["status"], result=rec.get("result"))
    return ok


def check(store: Store) -> dict:
    reg = store.load_registry()
    problems = []
    for mid, m in reg["markets"].items():
        h = store.load_history(mid)
        if h:
            ts = [p[0] for p in h["points"]]
            if ts != sorted(set(ts)):
                problems.append(f"history not sorted/unique: {mid}")
            if any(not (0 <= p[1] <= 1) for p in h["points"]):
                problems.append(f"price out of range: {mid}")
        if m["resolution"]["status"] == "final" and m["resolution"]["winner_index"] is None:
            problems.append(f"final without winner: {mid}")
    if problems:
        raise ValueError("; ".join(problems[:20]))
    return {"markets": len(reg["markets"]), "events": len(reg["events"]), "ok": True}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    cfg = load_config()
    store = Store(cfg.data_dir)
    ok = True
    if cmd in ("discover", "all"):
        c = Collector(cfg, store=store)
        ok &= _run("discover", c.run_discover, store, cfg, c)
    if cmd in ("resolve", "all"):
        c = Collector(cfg, store=store)
        ok &= _run("resolve", c.run_resolve, store, cfg, c)
    if cmd == "backfill":
        c = Collector(cfg, store=store)
        lim = int(argv[1]) if len(argv) > 1 else None
        ok &= _run("backfill", lambda: c.run_backfill(lim), store, cfg, c)
    if cmd in ("analyze", "all", "backfill"):
        ok &= _run("analyze", lambda: Analyzer(cfg, store).run(), store, cfg)
    if cmd == "check":
        ok &= _run("check", lambda: check(store), store, cfg)
    if cmd not in ("discover", "resolve", "backfill", "analyze", "all", "check"):
        print(__doc__)
        return 2
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
