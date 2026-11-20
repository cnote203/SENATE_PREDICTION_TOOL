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


# Largest shift donor history may apply to one score (score units). AUDIT.
MAX_DONOR_ADJUSTMENT = 0.75
# Score sources eligible for adjustment: scores set by an ideology mapping from a
# House record, with no Senate votes on the dimension. Senators with their own
# votes ("votes") already reflect whatever donors predict; new senators with no
# record ("imputed") are excluded because challenger PAC receipts mostly reflect
# incumbency and corporate-PAC pledges rather than policy.
ELIGIBLE_SOURCES = ("fitted",)


def adjust_scores(scores: pd.DataFrame, donors_df: pd.DataFrame, effects: pd.DataFrame) -> pd.DataFrame:
    """Shift eligible scores by the within-caucus donor slopes that passed the test.

    For each supported (category, dimension) effect:
        shift = slope * (log(1 + dollars) - mean among eligible senators in the same caucus)
    capped at +-MAX_DONOR_ADJUSTMENT. Adds <dim>_donor_adj and marks the source
    "fitted+donors". SDs are left unchanged (conservative).
    """
    out = scores.copy()
    if effects is None or effects.empty or donors_df is None or donors_df.empty:
        return out
    supported = effects[effects["supports_hypothesis"].astype(bool)]
    for _, e in supported.iterrows():
        dim, col = e["dimension"], f"fec_{e['category']}"
        src = f"{dim}_source"
        if dim not in out or col not in donors_df:
            continue
        adj_col = f"{dim}_donor_adj"
        if adj_col not in out:
            out[adj_col] = 0.0
        dollars = out["bioguide_id"].map(donors_df.set_index("bioguide_id")[col])
        eligible = out[src].isin(ELIGIBLE_SOURCES) & dollars.notna()
        if not eligible.any():
            continue
        x = np.log1p(dollars.clip(lower=0.0))
        centre = x[eligible].groupby(out.loc[eligible, "caucus"]).transform("mean")
        shift = (float(e["slope_per_log_dollar"]) * (x[eligible] - centre)).clip(
            -MAX_DONOR_ADJUSTMENT, MAX_DONOR_ADJUSTMENT)
        out.loc[eligible, adj_col] += shift
        out.loc[eligible, dim] = (out.loc[eligible, dim] + shift).clip(-2, 2).round(2)
        out.loc[eligible, src] = "fitted+donors"
    return out


def load_adjustment(processed_dir, congress: int):
    """Donor totals and tested effects, if fetch_donors.py has been run."""
    from pathlib import Path
    d, e = Path(processed_dir) / f"donors_{congress}.csv", Path(processed_dir) / "donor_effects.csv"
    if not (d.exists() and e.exists()):
        return None
    return pd.read_csv(d, dtype={"bioguide_id": str}), pd.read_csv(e)
