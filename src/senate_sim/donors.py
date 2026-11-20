"""Do PAC contributions explain where senators sit relative to their ideology?

For each donor category and the dimensions it plausibly bears on, regress each
senator's calibrated deviation (u_raw_score: how far their votes sit from what
DW-NOMINATE predicts) on log(1 + PAC dollars), within caucus. Demeaning by caucus
keeps the result from simply restating that Republicans get more defense money.

This is a correlation. PACs give to senators who already vote their way, so a
positive slope does not show that money moves votes. It does show whether donor
data adds information the ideology mapping misses, which is what matters for
deciding whether to put a donor term in the vote model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

# Which deviations each donor category is tested against, and the expected sign.
HYPOTHESES = [
    ("defense_contractor", "defense_budget", +1),
    ("defense_contractor", "nato_interventionism", +1),
    ("israel_policy", "arms_sales_oversight", -1),
]
MIN_N = 15


def test_donor_effects(donors: pd.DataFrame, deviations: pd.DataFrame, caucus: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for category, dimension, expected in HYPOTHESES:
        col = f"fec_{category}"
        if col not in donors:
            continue
        d = (deviations[deviations["dimension"] == dimension][["bioguide_id", "u_raw_score"]]
             .merge(donors[["bioguide_id", col]], on="bioguide_id", how="left")
             .merge(caucus, on="bioguide_id"))
        # Net refunds can make a total negative; treat them as no support.
        d[col] = d[col].fillna(0.0).clip(lower=0.0)
        if len(d) < MIN_N:
            continue
        d["x"] = np.log1p(d[col])
        for v in ("x", "u_raw_score"):
            d[v] = d[v] - d.groupby("caucus")[v].transform("mean")
        if d["x"].std() == 0:
            continue
        fit = stats.linregress(d["x"], d["u_raw_score"])
        rows.append({
            "category": category, "dimension": dimension, "n": len(d),
            "slope_per_log_dollar": fit.slope, "p_value": fit.pvalue, "r": fit.rvalue,
            "expected_sign": expected,
            "supports_hypothesis": bool(np.sign(fit.slope) == expected and fit.pvalue < 0.05),
        })
    return pd.DataFrame(rows)
