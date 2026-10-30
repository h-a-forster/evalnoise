import pytest

from evalnoise.validate import run_validation


@pytest.mark.slow
def test_quick_validation_checks_pass(tmp_path):
    """Every quick-profile Monte Carlo check lands near what the planner predicts."""
    results = run_validation(tmp_path, "quick")
    for r in results:
        for name, v in r["rates"].items():
            lo, hi = v["mc95"]
            # Known, documented gaps: percentile-bootstrap undercoverage with few items,
            # Satterthwaite liberal with few runs, conservative power on binary data.
            slack = 0.12 if r["kind"] in ("coverage", "binary") else 0.04
            assert lo - slack <= v["nominal"] <= hi + slack, (r["name"], name, v)
