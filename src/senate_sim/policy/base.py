"""Shared scoring engine for every policy module.

A module is a list of Dimensions. Each dimension turns a senator's ideology
point (DW-NOMINATE dim1, dim2) into a starting score on a -2..+2 scale. The
engine then:

1. scores senators with a voting record from their own DW-NOMINATE point,
2. imputes a point for senators with no record (see impute_ideology),
3. applies the module's hand-maintained override file,
4. attaches an uncertainty (standard deviation) to every score.

Healthcare, AI/Tech, Energy and Banking plug in by defining a new module file
with its own dimensions and override CSV; nothing here changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

SCALE_MIN, SCALE_MAX = -2.0, 2.0

# Uncertainty of a formula-based score, by where the ideology point came from.
# AUDIT: these are judgment calls; widen them if back-tests show overconfidence.
SD_BY_SOURCE = {"Senate": 0.25, "House": 0.45, "imputed": 0.80}

# Floor on the SD of a score estimated from the senator's own votes.
MIN_VOTES_SD = 0.15

# Extra SD for a House-derived ideology point under a fitted mapping (House to
# Senate translation). AUDIT: judgment until House-Senate switchers are studied.
HOUSE_EXTRA_SD = 0.30

# Share of the distance to the centre (dim1 = 0) an imputed senator is moved
# when the state's other senator belongs to the opposite caucus.
# AUDIT: a crude proxy for state partisanship until real state lean data is added.
CROSS_PRESSURE_SHIFT = 0.35

OVERRIDE_COLUMNS = ["bioguide_id", "name", "dimension", "score", "sd", "evidence", "roll_calls", "verified"]


@dataclass(frozen=True)
class Dimension:
    name: str
    low: str   # what -2 means
    high: str  # what +2 means
    formula: Callable[[np.ndarray, np.ndarray], np.ndarray]  # prior, used until calibrated
    calibrate: bool = True          # False: no informative roll calls; keep the prior formula
    prior_sd: float | None = None   # SD floor when the prior formula is used


@dataclass(frozen=True)
class PolicyModule:
    name: str
    dimensions: list[Dimension]
    override_path: Path
    calibration_path: Path | None = None
    notes: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def dimension_names(self) -> list[str]:
        return [d.name for d in self.dimensions]


def impute_ideology(baseline: pd.DataFrame) -> pd.DataFrame:
    """Return dim1, dim2 and their source for every senator.

    Senators with a record keep their own point. Senators without one get the
    median dim1 of the sitting senators in their caucus, pulled toward the
    centre when their state's other senator is from the opposite caucus, and
    dim2 = 0. Imputation never uses other incoming senators.
    """
    df = baseline[["bioguide_id", "state", "caucus", "nominate_dim1", "nominate_dim2"]].copy()
    chamber = baseline.get("score_chamber")
    df["ideology_source"] = np.where(
        df["nominate_dim1"].notna(),
        chamber.fillna("Senate") if chamber is not None else "Senate",
        "imputed",
    )

    has = df["nominate_dim1"].notna()
    medians = df[has].groupby("caucus")["nominate_dim1"].median()

    dim1, dim2 = df["nominate_dim1"].copy(), df["nominate_dim2"].copy()
    for idx in df.index[~has]:
        row = df.loc[idx]
        point = medians.get(row["caucus"], 0.0)
        colleagues = df[(df["state"] == row["state"]) & (df.index != idx)]
        if (colleagues["caucus"] != row["caucus"]).any():
            point *= 1 - CROSS_PRESSURE_SHIFT
        dim1.loc[idx] = point
        dim2.loc[idx] = 0.0

    df["dim1"], df["dim2"] = dim1.astype(float), dim2.fillna(0.0).astype(float)
    return df[["bioguide_id", "dim1", "dim2", "ideology_source"]]


def load_overrides(module: PolicyModule, valid_ids: set[str], strict: bool = True) -> pd.DataFrame:
    if not module.override_path.exists():
        return pd.DataFrame(columns=OVERRIDE_COLUMNS)
    ov = pd.read_csv(module.override_path, dtype={"bioguide_id": str})
    missing = set(OVERRIDE_COLUMNS) - set(ov.columns)
    if missing:
        raise ValueError(f"{module.override_path.name} is missing columns: {sorted(missing)}")
    bad_dim = set(ov["dimension"]) - set(module.dimension_names)
    if bad_dim:
        raise ValueError(f"Unknown dimensions in overrides: {sorted(bad_dim)}")
    bad_id = set(ov["bioguide_id"]) - valid_ids
    if bad_id and strict:
        raise ValueError(f"Override Bioguide IDs not in the baseline: {sorted(bad_id)}")
    ov = ov[ov["bioguide_id"].isin(valid_ids)]
    if ov.duplicated(["bioguide_id", "dimension"]).any():
        raise ValueError("A senator has two overrides for the same dimension.")
    out_of_range = ov[(ov["score"] < SCALE_MIN) | (ov["score"] > SCALE_MAX)]
    if not out_of_range.empty:
        raise ValueError(f"Override scores outside -2..+2: {out_of_range['bioguide_id'].tolist()}")
    return ov


def score(
    baseline: pd.DataFrame, module: PolicyModule, calibration: dict | None = None,
    strict_overrides: bool = True,
    donor_adjustment: tuple[pd.DataFrame, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Return one row per senator: <dim>, <dim>_sd and <dim>_source for each dimension.

    Sources: votes (calibrated mapping plus the senator's own deviation, estimated
    from their votes), fitted (calibrated mapping only: no votes on the dimension,
    e.g. House-only records), formula (prior), imputed (no record), override.
    """
    from senate_sim.policy.calibration import latent_to_score

    calibration = calibration or {}
    ideo = impute_ideology(baseline)
    out = baseline[["bioguide_id", "name", "state", "caucus"]].merge(ideo, on="bioguide_id")
    src = out["ideology_source"]
    d1, d2 = out["dim1"].to_numpy(), out["dim2"].to_numpy()

    for dim in module.dimensions:
        fit = calibration.get(dim.name) if dim.calibrate else None
        if fit:
            raw = latent_to_score(d1, d2, fit)
            sigma = float(fit["sigma_score"])
            own = fit.get("senators", {})
            scored = pd.Series(np.clip(raw, SCALE_MIN, SCALE_MAX), index=out.index)
            caucus_var = scored[src != "imputed"].groupby(out["caucus"]).var()
            sd = np.select(
                [src == "Senate", src == "House"],
                [sigma, np.sqrt(sigma ** 2 + HOUSE_EXTRA_SD ** 2)],
                default=np.sqrt(sigma ** 2 + out["caucus"].map(caucus_var).fillna(0.5)),
            )
            label = np.where(src == "imputed", "imputed", "fitted")
            # Senators with their own votes on this dimension: mapping + their deviation.
            u = out["bioguide_id"].map(lambda b: own.get(b, {}).get("u")).astype(float)
            se = out["bioguide_id"].map(lambda b: own.get(b, {}).get("se")).astype(float)
            has = u.notna().to_numpy() & (src != "imputed").to_numpy()
            raw = np.where(has, raw + u.fillna(0).to_numpy(), raw)
            sd = np.where(has, np.maximum(se.fillna(0).to_numpy(), MIN_VOTES_SD), sd).astype(float)
            label = np.where(has, "votes", label)
        else:
            raw = dim.formula(d1, d2)
            sd = src.map(SD_BY_SOURCE).astype(float).to_numpy()
            if dim.prior_sd:
                sd = np.maximum(sd, dim.prior_sd)
            label = np.where(src == "imputed", "imputed", "formula")
        out[dim.name] = np.clip(raw, SCALE_MIN, SCALE_MAX).round(2)
        out[f"{dim.name}_sd"] = np.round(sd, 3)
        out[f"{dim.name}_source"] = label

    if donor_adjustment is not None:
        from senate_sim.donors import adjust_scores
        out = adjust_scores(out, *donor_adjustment)

    overrides = load_overrides(module, set(out["bioguide_id"]), strict=strict_overrides)
    pos = {bid: i for i, bid in enumerate(out["bioguide_id"])}
    for _, o in overrides.iterrows():
        i = pos[o["bioguide_id"]]
        out.loc[i, o["dimension"]] = float(o["score"])
        out.loc[i, f"{o['dimension']}_sd"] = float(o["sd"])
        out.loc[i, f"{o['dimension']}_source"] = "override"
    return out
