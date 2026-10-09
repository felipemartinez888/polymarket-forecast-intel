"""Structured JSON-lines logging to stderr."""
from __future__ import annotations

import json
import sys
import time


def log(level: str, msg: str, **fields) -> None:
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "level": level, "msg": msg}
    rec.update(fields)
    print(json.dumps(rec, default=str), file=sys.stderr, flush=True)


def info(msg: str, **f) -> None:
    log("info", msg, **f)


def warn(msg: str, **f) -> None:
    log("warn", msg, **f)


def error(msg: str, **f) -> None:
    log("error", msg, **f)
