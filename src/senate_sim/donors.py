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

# Donor categories: display label and the policy sectors they bear on.
CATEGORIES = {
    "defense_contractor": ("Defense contractor PACs", ["foreign_policy"]),
    "israel_policy": ("Israel-policy PACs", ["foreign_policy"]),
    "pharma": ("Drugmaker PACs", ["healthcare"]),
    "health_insurers": ("Health insurer PACs", ["healthcare"]),
    "health_providers": ("Hospital and doctor PACs", ["healthcare"]),
    "oil_gas": ("Oil, gas and coal PACs", ["energy"]),
    "clean_energy": ("Clean energy PACs", ["energy"]),
    "banks": ("Bank and credit union PACs", ["banking"]),
    "crypto": ("Crypto industry PACs", ["banking", "tech"]),
    "big_tech": ("Big tech PACs", ["tech"]),
}

# Which deviations each donor category is tested against, and the expected sign.
# Only calibrated dimensions have deviations, so uncalibrated ones (drug prices,
# all of tech) are shown in the app but not tested. AUDIT: the expected signs
# are judgment calls written before seeing the data.
HYPOTHESES = [
    ("defense_contractor", "defense_budget", +1),
    ("defense_contractor", "nato_interventionism", +1),
    ("israel_policy", "arms_sales_oversight", -1),
    ("health_insurers", "coverage_expansion", +1),   # insurers gain from subsidized enrollment
    ("health_providers", "coverage_expansion", +1),  # hospitals gain from Medicaid coverage
    ("pharma", "coverage_expansion", +1),
    ("oil_gas", "clean_energy", -1),
    ("clean_energy", "clean_energy", +1),
    ("banks", "consumer_finance_regulation", -1),
    ("crypto", "crypto_support", +1),
    ("banks", "crypto_support", -1),
]
MIN_N = 15
ALPHA = 0.05


def _dimension_sector(dimension: str) -> str:
    from senate_sim import policy
    for m in policy.all_modules():
        if any(d.name == dimension for d in m.dimensions):
            return m.name
    return "other"


def holm(p: pd.Series) -> pd.Series:
    """Holm step-down adjusted p-values (controls the chance of any false positive)."""
    order = p.sort_values().index
    m = len(p)
    adj, running = pd.Series(index=p.index, dtype=float), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p[i]))
        adj[i] = running
    return adj


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
        })
    out = pd.DataFrame(rows, columns=["category", "dimension", "n", "slope_per_log_dollar", "p_value", "r",
                                      "expected_sign"])
    if out.empty:
        return out.assign(sector=[], p_holm=[], supports_hypothesis=[])
    # Each sector's tests are one family: more hypotheses must not mean more chance hits.
    out["sector"] = out["dimension"].map(_dimension_sector)
    out["p_holm"] = out.groupby("sector", group_keys=False)["p_value"].apply(holm)
    out["supports_hypothesis"] = (np.sign(out["slope_per_log_dollar"]) == out["expected_sign"]) & (out["p_holm"] < ALPHA)
    return out


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


def merge_pacs(existing: pd.DataFrame | None, found: pd.DataFrame) -> pd.DataFrame:
    """Add newly found PACs to the reviewed list without touching reviewed rows."""
    if existing is None or existing.empty:
        return found.reset_index(drop=True)
    new = found[~found["committee_id"].isin(set(existing["committee_id"]))]
    return pd.concat([existing, new.astype(str)], ignore_index=True).sort_values(["category", "name"]).reset_index(drop=True)


def load_adjustment(processed_dir, congress: int):
    """Donor totals and tested effects, if fetch_donors.py has been run."""
    from pathlib import Path
    d, e = Path(processed_dir) / f"donors_{congress}.csv", Path(processed_dir) / "donor_effects.csv"
    if not (d.exists() and e.exists()):
        return None
    return pd.read_csv(d, dtype={"bioguide_id": str}), pd.read_csv(e)
