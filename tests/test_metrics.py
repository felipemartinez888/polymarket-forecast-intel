import math

import pytest

from pipeline import metrics as M


def test_binary_brier_known_values():
    assert M.brier_binary(0.7, 1) == pytest.approx(0.09)
    assert M.brier_binary(0.7, 0) == pytest.approx(0.49)
    assert M.brier_binary(0.5, 1) == 0.25
    assert M.brier_binary(1.0, 1) == 0.0
    with pytest.raises(ValueError):
        M.brier_binary(1.2, 1)
    with pytest.raises(ValueError):
        M.brier_binary(0.5, 2)


def test_multiclass_brier_known_values_and_scale():
    assert M.brier_multiclass([0.7, 0.2, 0.1], 0) == pytest.approx(0.14)
    assert M.brier_multiclass([0.0, 1.0], 0) == pytest.approx(2.0)  # worst case = 2
    K = 4
    assert M.brier_multiclass([1 / K] * K, 2) == pytest.approx(1 - 1 / K)  # uniform reference
    # binary case of the multiclass score is exactly 2x the binary Brier
    assert M.brier_multiclass([0.7, 0.3], 0) == pytest.approx(2 * M.brier_binary(0.7, 1))
    with pytest.raises(ValueError):
        M.brier_multiclass([0.5, 0.6], 0)


def test_normalization():
    norm, s = M.normalize([0.15, 0.80, 0.04, 0.03])
    assert s == pytest.approx(1.02)
    assert sum(norm) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        M.normalize([0.0, 0.0])
    with pytest.raises(ValueError):
        M.normalize([0.5, None])


def test_log_loss_clipping():
    assert M.log_loss_binary(0.0, 1, 0.01) == pytest.approx(-math.log(0.01))
    assert M.log_loss_binary(1.0, 1, 0.01) == pytest.approx(-math.log(0.99))
    assert M.log_loss_multiclass([0.1, 0.9], 1, 0.01) == pytest.approx(-math.log(0.9))


def test_directional_with_no_call_band():
    assert M.directional(0.8, 1) == 1
    assert M.directional(0.8, 0) == 0
    assert M.directional(0.52, 1) is None


def test_calibration_binning_edges():
    pairs = [(0.0, 0), (0.1, 0), (0.0999, 1), (0.95, 1), (1.0, 1), (0.55, 0), (0.55, 1)]
    bins = M.calibration_bins(pairs, 10, min_n=10)
    assert bins[0]["n"] == 2 and bins[0]["events"] == 1          # 0.0 and 0.0999
    assert bins[1]["n"] == 1                                       # 0.1 belongs to 10-20%
    assert bins[9]["n"] == 2 and bins[9]["observed_freq"] == 1.0   # 1.0 lands in last bin
    assert bins[5]["mean_forecast"] == pytest.approx(0.55) and bins[5]["observed_freq"] == 0.5
    assert bins[5]["gap"] == pytest.approx(-0.05)
    assert all(b["low_sample"] for b in bins)
    assert bins[3]["n"] == 0 and bins[3]["observed_freq"] is None


def test_wilson_interval():
    lo, hi = M.wilson_interval(7, 10)
    assert lo == pytest.approx(0.3968, abs=1e-3) and hi == pytest.approx(0.8922, abs=1e-3)
    assert M.wilson_interval(0, 0) is None


def test_skill_scores_and_bootstrap_determinism():
    model, ref = [0.04, 0.09, 0.01], [0.25, 0.25, 0.25]
    assert M.skill_score(model, ref) == pytest.approx(1 - 0.14 / 0.75)
    a = M.bootstrap_skill_ci(model, ref, 500, seed=1)
    b = M.bootstrap_skill_ci(model, ref, 500, seed=1)
    assert a == b
    ci = M.bootstrap_mean_ci([0.1, 0.2, 0.3, 0.4], 1000, seed=3)
    assert ci[0] <= 0.25 <= ci[1]
    assert M.bootstrap_mean_ci([0.1], 100, 1) is None


def test_time_weighted_mean_and_volatility():
    pts = [[0, 0.2], [10, 0.6]]
    assert M.time_weighted_mean(pts, 0, 20) == pytest.approx(0.4)
    assert M.time_weighted_mean(pts, 5, 10) == pytest.approx(0.2)
    flat = [[i * 86400, 0.5] for i in range(10)]
    assert M.path_volatility(flat, 0, 10 * 86400) == pytest.approx(0.0)
    assert M.path_volatility(flat[:2], 0, 2 * 86400) is None


def test_ece():
    bins = M.calibration_bins([(0.7, 1), (0.7, 0)], 10)
    assert M.expected_calibration_error(bins) == pytest.approx(0.2)
