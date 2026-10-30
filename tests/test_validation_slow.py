import math

import pytest

from evalnoise.validate import run_validation

# Known, documented gaps (REPORT.md "Validation"): (direction, extra allowance). The rate
# may miss its nominal value in that direction (+1 above, -1 below) by up to the allowance
# beyond the 3 Monte Carlo SEs every quantity gets.
KNOWN = {
    # Pass/fail at 60 to 70% pass and gains near 90%: the base-rate variance is kept, so
    # power is above target (conservative).
    ("binary-t50-k3", "at_mde"): (1, 0.1),
    ("binary-t30-k1", "at_mde"): (1, 0.1),
    ("binary-p90-t50-k3-up", "at_mde"): (1, 0.2),
    # Satterthwaite t with three runs per arm: somewhat liberal.
    ("runs-t60-r3", "null"): (1, 0.05),
    # Percentile bootstrap undercovers with 40 items, and item x run with 60 items, 3 runs.
    ("coverage-t40-a2-k3", "item"): (-1, 0.1),
    ("coverage-t40-a2-k3", "item_arm"): (-1, 0.15),
    ("coverage-t60-a3-r3", "item_run"): (-1, 0.12),
}


@pytest.mark.slow
def test_quick_validation_checks_pass(tmp_path):
    """Every quick-profile Monte Carlo check lands within 3 Monte Carlo SEs of what the
    planner predicts, except the named known gaps, which may miss only in their direction."""
    results = run_validation(tmp_path, "quick")
    seen = set()
    for r in results:
        for name, v in r["rates"].items():
            nominal = v["nominal"]
            tol = 3 * math.sqrt(nominal * (1 - nominal) / r["sims"])
            sign, extra = KNOWN.get((r["name"], name), (0, 0.0))
            seen.add((r["name"], name))
            diff = v["rate"] - nominal
            assert -tol - (extra if sign < 0 else 0) <= diff, (r["name"], name, v)
            assert diff <= tol + (extra if sign > 0 else 0), (r["name"], name, v)
    assert set(KNOWN) <= seen
