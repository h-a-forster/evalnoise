import math

import numpy as np
import pandas as pd
import pytest

from evalnoise.components import Components, bootstrap, estimate
from evalnoise.reml import reml
from evalnoise.simulate import simulate

TRUE = Components(item=4.0, item_arm=1.0, run=0.5, item_run=0.7, within=2.0)
NAMES = ("item", "item_arm", "run", "item_run", "within")


def _mean_estimates(sims, **kw):
    vals = np.array(
        [
            [getattr(estimate(simulate(TRUE, seed=s, **kw)).components, n) for n in NAMES]
            for s in range(sims)
        ]
    )
    return vals.mean(axis=0), vals.std(axis=0, ddof=1) / math.sqrt(sims)


@pytest.mark.parametrize(
    "layout, expected, absorbed",
    [
        # Runs and repeats: everything identified.
        (dict(runs=3, repeats=2), (4.0, 1.0, 0.5, 0.7, 2.0), {}),
        # Replicate runs, one trial per run: within folds into item x run.
        (dict(runs=3, repeats=1), (4.0, 1.0, 0.5, 2.7, None), {"within": "item_run"}),
        # Repeats in one run: item x run folds into item x arm.
        (dict(runs=1, repeats=3), (4.0, 1.7, None, None, 2.0), {"item_run": "item_arm"}),
        # One trial per item and arm: all trial noise folds into item x arm.
        (
            dict(runs=1, repeats=1),
            (4.0, 3.7, None, None, None),
            {"item_run": "item_arm", "within": "item_arm"},
        ),
    ],
)
def test_moment_estimates_are_unbiased(layout, expected, absorbed):
    mean, se = _mean_estimates(250, tasks=30, arms=3, **layout)
    for name, m, s, e in zip(NAMES, mean, se, expected, strict=True):
        if e is None:
            assert math.isnan(m), name
        else:
            assert abs(m - e) < 4.5 * s + 1e-9, (name, m, e, s)
    df = simulate(TRUE, tasks=30, arms=3, seed=0, **layout)
    assert estimate(df).components.absorbed == absorbed


def test_run_term_degrees_of_freedom_balanced():
    # Regression: rounding left a tiny eigenvalue counted as rank, giving R instead of R - 1
    # run degrees of freedom and a downward-biased run variance.
    df = simulate(TRUE, tasks=20, arms=1, runs=3, seed=1)
    rt = estimate(df).run_term
    assert rt.df == 2
    assert rt.k == pytest.approx(20 * 2)
    assert rt.df_res == 3 * 20 - 20 - 2


def test_run_component_unbiased_with_partial_runs():
    # A third run that covers only part of the items (a run still in progress).
    vals = []
    for s in range(400):
        df = simulate(TRUE, tasks=24, arms=2, runs=3, seed=s)
        drop = (df["run"] == "r2") & (df["item"].str[1:].astype(int) >= 8)
        vals.append(estimate(df[~drop]).components.run)
    vals = np.array(vals)
    assert abs(vals.mean() - TRUE.run) < 4.5 * vals.std(ddof=1) / math.sqrt(len(vals))


def test_reml_equals_moments_on_balanced_data():
    df = simulate(TRUE, tasks=25, arms=2, runs=2, repeats=2, seed=3)
    m = estimate(df).components
    r = reml(df)
    for n in NAMES:
        if getattr(m, n) > 0.05:  # interior solutions coincide
            assert getattr(r, n) == pytest.approx(getattr(m, n), rel=2e-3), n
    assert r.absorbed == m.absorbed


def test_reml_matches_statsmodels_on_unbalanced_data():
    smf = pytest.importorskip("statsmodels.formula.api")
    df = simulate(TRUE, tasks=12, arms=2, runs=1, repeats=3, seed=11)
    df = df.drop(index=[0, 5, 17, 40]).reset_index(drop=True)
    ours = reml(df)
    d = df.assign(one=1, ia=df["item"] + ":" + df["arm"])
    model = smf.mixedlm(
        "score ~ 0 + C(arm)",
        d,
        groups="one",
        vc_formula={"item": "0 + C(item)", "ia": "0 + C(ia)"},
        re_formula="0",
    )
    fit = model.fit(reml=True, method=["lbfgs"])
    sm = dict(zip(model.exog_vc.names, fit.vcomp, strict=True))
    assert ours.item == pytest.approx(sm["item"], rel=1e-3, abs=1e-4)
    assert ours.item_arm == pytest.approx(sm["ia"], rel=1e-3, abs=1e-4)
    assert ours.within == pytest.approx(fit.scale, rel=1e-3)


def test_single_arm_and_pairs():
    df = simulate(TRUE, tasks=30, arms=2, repeats=2, effect=1.5, seed=2)
    est = estimate(df, pairs=[("arm1", "arm0")])
    p = est.pairs["arm1 - arm0"]
    means = df.groupby("arm")["score"].mean()
    assert p["difference"] == pytest.approx(means["arm1"] - means["arm0"])
    one = estimate(df, arms=["arm0"]).components
    assert math.isnan(one.item_arm) and one.absorbed == {"item_run": "item"}


def test_bootstrap_is_seeded_and_brackets_estimate():
    df = simulate(TRUE, tasks=30, arms=2, runs=2, repeats=2, seed=4)
    a = bootstrap(df, draws=60, seed=9)
    b = bootstrap(df, draws=60, seed=9)
    assert a.components == b.components
    est = estimate(df).components
    lo, hi = a.components["item"]
    assert lo < est.item < hi


def test_bootstrap_resamples_clusters_not_items():
    # Two items per cluster with identical scores: resampling clusters keeps them together,
    # so the item variance of every draw is computed from duplicated pairs.
    rows = []
    for c in range(20):
        for j in range(2):
            for arm in ("a", "b"):
                for k in range(2):
                    rows.append(
                        {
                            "item": f"c{c}i{j}",
                            "cluster": f"c{c}",
                            "arm": arm,
                            "run": "r",
                            "repeat": k,
                            "score": float(c) + 0.1 * k,
                        }
                    )
    from evalnoise.data import validate

    df = validate(pd.DataFrame(rows))
    b = bootstrap(df, draws=50, seed=0)
    assert b.draws == 50
    assert estimate(df).clusters == 20


def test_errors():
    df = simulate(TRUE, tasks=5, arms=2, seed=0)
    from evalnoise.data import DataError

    with pytest.raises(DataError, match="not in data"):
        estimate(df, arms=["nope"])
    with pytest.raises(DataError, match="fewer than 2 items"):
        estimate(df[df["item"] == "t0"])


def test_cluster_se_tracks_clustered_item_effects():
    # Pairs of items share an extra item x arm effect, so the 40 items are 20 clusters.
    # The cluster SE should match the spread of the difference; the item SE understates it.
    diffs, se_items, se_clusters = [], [], []
    rng = np.random.default_rng(3)
    for _ in range(400):
        df = simulate(Components(1.0, 0.2, 0.0, 0.0, 0.5), tasks=40, seed=rng)
        shared = rng.normal(0, 2.0, 20)
        cl = df["item"].str[1:].astype(int) // 2
        df["cluster"] = "c" + cl.astype(str)
        df.loc[df["arm"] == "arm1", "score"] += shared[cl[df["arm"] == "arm1"]]
        p = estimate(df, pairs=[("arm1", "arm0")]).pairs["arm1 - arm0"]
        diffs.append(p["difference"])
        se_items.append(p["se_items"])
        se_clusters.append(p["se_clusters"])
        assert p["clusters"] == 20 and p["items_differing"] == 40
    true_sd = np.std(diffs, ddof=1)
    assert abs(np.sqrt(np.mean(np.square(se_clusters))) / true_sd - 1) < 0.12
    assert np.sqrt(np.mean(np.square(se_items))) / true_sd < 0.8
    # One item per cluster: the two SEs coincide.
    p = estimate(simulate(TRUE, tasks=15, seed=0), pairs=[("arm1", "arm0")]).pairs["arm1 - arm0"]
    assert p["se_clusters"] == pytest.approx(p["se_items"])


def test_run_terms_per_arm_and_pooled():
    df = simulate(TRUE, tasks=30, arms=3, runs=3, seed=4)
    est = estimate(df)
    assert set(est.run_terms) == {"arm0", "arm1", "arm2"}
    for arm, t in est.run_terms.items():
        alone = estimate(df[df["arm"] == arm]).run_term
        assert t.variance() == pytest.approx(alone.variance())
    assert est.components.run == pytest.approx(est.run_term.variance())
