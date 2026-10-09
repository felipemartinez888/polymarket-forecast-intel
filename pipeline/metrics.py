"""Forecast-verification metrics. Pure functions, no I/O, deterministic.

Scales (documented in docs/METHODOLOGY.md):
  binary Brier       (p - o)^2                       range [0, 1]; uninformed 0.5 forecast = 0.25
  multiclass Brier   sum_k (p_k - o_k)^2              range [0, 2]; uniform 1/K forecast = 1 - 1/K
  Brier skill score  1 - BS / BS_ref                  (-inf, 1]; > 0 beats the reference
"""
from __future__ import annotations

import math
import random


def brier_binary(p: float, o: int) -> float:
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"probability out of range: {p}")
    if o not in (0, 1):
        raise ValueError(f"outcome must be 0/1: {o}")
    return (p - o) ** 2


def normalize(probs: list[float]) -> tuple[list[float], float]:
    """Normalize a probability vector to sum to 1. Returns (normalized, raw_sum)."""
    if any(p is None or p < 0 for p in probs):
        raise ValueError("invalid probability vector")
    s = sum(probs)
    if s <= 0:
        raise ValueError("probability vector sums to zero")
    return [p / s for p in probs], s


def brier_multiclass(probs: list[float], winner: int) -> float:
    """Original (Brier 1950) multiclass score over a normalized vector. Range [0, 2]."""
    if not 0 <= winner < len(probs):
        raise ValueError("winner index out of range")
    if abs(sum(probs) - 1.0) > 1e-6:
        raise ValueError("probabilities must be normalized")
    return sum((p - (1 if i == winner else 0)) ** 2 for i, p in enumerate(probs))


def log_loss_binary(p: float, o: int, clip: float) -> float:
    q = min(max(p, clip), 1 - clip)
    return -(o * math.log(q) + (1 - o) * math.log(1 - q))


def log_loss_multiclass(probs: list[float], winner: int, clip: float) -> float:
    return -math.log(min(max(probs[winner], clip), 1 - clip))


def directional(p: float, o: int, threshold: float = 0.5, no_call_band: float = 0.05) -> int | None:
    """1 = correct call, 0 = wrong, None = no call (|p - threshold| < band)."""
    if abs(p - threshold) < no_call_band:
        return None
    return int((p > threshold) == bool(o))


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def wilson_interval(k: int, n: int, z: float = 1.959964) -> tuple[float, float] | None:
    if n == 0:
        return None
    ph = k / n
    den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def calibration_bins(pairs: list[tuple[float, int]], n_bins: int = 10, min_n: int = 10) -> list[dict]:
    """Equal-width bins on [0,1]; bin i covers [i/n, (i+1)/n), last bin closed at 1.0."""
    bins = [{"lo": i / n_bins, "hi": (i + 1) / n_bins, "ps": [], "os": []} for i in range(n_bins)]
    for p, o in pairs:
        i = min(int(p * n_bins), n_bins - 1)
        bins[i]["ps"].append(p)
        bins[i]["os"].append(o)
    out = []
    for b in bins:
        n = len(b["ps"])
        k = sum(b["os"])
        mp = mean(b["ps"])
        freq = k / n if n else None
        ci = wilson_interval(k, n)
        out.append({
            "bin": f"{int(round(b['lo']*100))}-{int(round(b['hi']*100))}%",
            "lo": b["lo"], "hi": b["hi"], "n": n, "events": k,
            "mean_forecast": mp, "observed_freq": freq,
            "gap": (freq - mp) if n else None,
            "ci_low": ci[0] if ci else None, "ci_high": ci[1] if ci else None,
            "low_sample": n < min_n,
        })
    return out


def expected_calibration_error(bins: list[dict]) -> float | None:
    total = sum(b["n"] for b in bins)
    if not total:
        return None
    return sum(b["n"] * abs(b["gap"]) for b in bins if b["n"]) / total


def bootstrap_mean_ci(xs: list[float], samples: int, seed: int, alpha: float = 0.05) -> tuple[float, float] | None:
    if len(xs) < 2:
        return None
    rng = random.Random(seed)
    n = len(xs)
    means = sorted(sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(samples))
    lo = means[int(alpha / 2 * samples)]
    hi = means[min(samples - 1, int((1 - alpha / 2) * samples))]
    return lo, hi


def skill_score(model: list[float], ref: list[float]) -> float | None:
    if not model or len(model) != len(ref):
        return None
    r = sum(ref)
    if r == 0:
        return None
    return 1 - sum(model) / r


def bootstrap_skill_ci(model: list[float], ref: list[float], samples: int, seed: int,
                       alpha: float = 0.05) -> tuple[float, float] | None:
    """Paired (event-level) bootstrap CI for the Brier skill score."""
    n = len(model)
    if n < 2 or n != len(ref):
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(samples):
        idx = [rng.randrange(n) for _ in range(n)]
        r = sum(ref[i] for i in idx)
        if r == 0:
            continue
        vals.append(1 - sum(model[i] for i in idx) / r)
    if not vals:
        return None
    vals.sort()
    return vals[int(alpha / 2 * len(vals))], vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))]


def path_volatility(points: list[list], start_ts: int, end_ts: int, step_s: int = 86400) -> float | None:
    """Std-dev of step-sampled (default daily) probability changes in [start, end). Units: probability."""
    sampled = []
    j = 0
    t = start_ts
    last = None
    while t < end_ts:
        while j < len(points) and points[j][0] <= t:
            last = points[j][1]
            j += 1
        if last is not None:
            sampled.append(last)
        t += step_s
    if len(sampled) < 3:
        return None
    d = [b - a for a, b in zip(sampled, sampled[1:])]
    m = sum(d) / len(d)
    return math.sqrt(sum((x - m) ** 2 for x in d) / (len(d) - 1))


def time_weighted_mean(points: list[list], start_ts: int, end_ts: int) -> float | None:
    """Time-weighted average probability over [start, end) using step (last-observation) interpolation."""
    if end_ts <= start_ts:
        return None
    acc = 0.0
    covered = 0
    prev = None
    for t, p in points:
        if t >= end_ts:
            break
        if prev is not None:
            a, b = max(prev[0], start_ts), min(t, end_ts)
            if b > a:
                acc += prev[1] * (b - a)
                covered += b - a
        prev = (t, p)
    if prev is not None and prev[0] < end_ts:
        a = max(prev[0], start_ts)
        if end_ts > a:
            acc += prev[1] * (end_ts - a)
            covered += end_ts - a
    return acc / covered if covered else None
