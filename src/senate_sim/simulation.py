"""Monte Carlo vote model and procedural gates for a single measure.

For senator i, measure j, run r:

    y*_ijr = a_jr + b * (theta_i + e_i,r) + gamma * CP_i + h_caucus(i),j,r + v_ijr
    vote on the +2 side if y* > 0

    theta_i   the senator's score on the measure's dimension (-2..+2)
    e_i,r     N(0, sd_i): drawn ONCE per run and shared by every measure on that
              dimension, so a senator stays coherent within a run
    a_jr      the measure's cutpoint, drawn per run from its family's fitted items
              (so uncertainty about the measure itself carries through)
    b         discrimination per score unit, from the calibration scale
    gamma     effect of being in the President's party (calibrated when identified)
    h         caucus-level shock N(0, tau) per measure and run: correlated swings,
              which independent draws would miss at 49-51 margins
    v         idiosyncratic N(0, 1) probit noise
    attendance  each senator present with probability ATTENDANCE

Procedural gates (Senate):
    majority      yeas > nays among those voting; a tie goes the Vice President's
                  way, i.e. the White House's position
    cloture       60 yeas (three-fifths of 100 sworn)
    two_thirds    yeas >= 2/3 of those voting (treaties, veto overrides)

A joint resolution of disapproval (Arms Export Control Act s.36) or war powers
resolution moves on privileged, simple-majority motions: discharge, then passage.
If it clears both chambers the President vetoes it with probability P_VETO, and
it survives only if both chambers override by two-thirds. The House is not
modelled member by member: its passage and override probabilities are inputs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ATTENDANCE = 0.97
P_VETO_IF_OPPOSED = 0.97
DEFAULT_B = 1.5  # per score unit, when no calibration exists


@dataclass
class Stage:
    name: str
    threshold: str  # "majority" | "cloture" | "two_thirds"


@dataclass
class Measure:
    name: str
    dimension: str
    family: str | None
    plus_side: str                 # "Yea" if voting Yea is the +2 side of the dimension
    stages: list[Stage]
    president_position: str | None  # "oppose" | "support" | None
    veto_possible: bool = False
    tau: float = 0.15               # caucus shock SD; larger for issues whose salience is moving
    alpha_shift: float = 0.0        # manual cutpoint shift (e.g. for salience), latent units
    house_pass_prob: float = 1.0    # P(House passes) given Senate passage; 1.0 = not modelled
    house_override_prob: float = 0.05
    # "family": cutpoint drawn from all of the family's fitted votes (stable issues).
    # "latest": cutpoint starts at the family's most recent vote and drifts as a random
    #           walk to `as_of` (issues whose support is moving, e.g. Israel arms sales).
    alpha_mode: str = "family"
    as_of: str = "2027-03-01"
    notes: str = ""


PRESETS = {
    "israel_arms_disapproval": Measure(
        "Joint resolution of disapproval: arms sale to Israel", "arms_sales_oversight",
        "israel_fms", "Yea", [Stage("discharge", "majority"), Stage("passage", "majority")],
        president_position="oppose", veto_possible=True, tau=0.5, house_pass_prob=0.3,
        alpha_mode="latest",
        notes="Support moved from 15 to 40 yeas in a year: the cutpoint starts at the latest "
              "vote and drifts from there, and tau is wide.",
    ),
    "gulf_arms_disapproval": Measure(
        "Joint resolution of disapproval: arms sale to a Gulf state", "arms_sales_oversight",
        "gulf_fms", "Yea", [Stage("discharge", "majority"), Stage("passage", "majority")],
        president_position="oppose", veto_possible=True, tau=0.3, house_pass_prob=0.3,
    ),
    "iran_war_powers": Measure(
        "War powers joint resolution (Iran)", "nato_interventionism", "war_powers_iran", "Nay",
        [Stage("discharge", "majority"), Stage("passage", "majority")],
        president_position="oppose", veto_possible=True, tau=0.15, house_pass_prob=0.5,
    ),
    "ndaa_passage": Measure(
        "NDAA: cloture and passage", "defense_budget", "ndaa_fy26", "Yea",
        [Stage("cloture", "cloture"), Stage("passage", "majority")],
        president_position="support", veto_possible=False, tau=0.2,
    ),
}


def _passes(yeas: np.ndarray, nays: np.ndarray, threshold: str, tie_passes: bool) -> np.ndarray:
    if threshold == "majority":
        return (yeas > nays) | ((yeas == nays) & tie_passes)
    if threshold == "cloture":
        return yeas >= 60
    if threshold == "two_thirds":
        return yeas >= np.ceil(2 * (yeas + nays) / 3)
    raise ValueError(f"Unknown threshold {threshold}")


def measure_parameters(measure: Measure, calibration: dict | None) -> dict:
    """Cutpoint distribution, discrimination and gamma for a measure, from calibration if present."""
    fit = (calibration or {}).get(measure.dimension)
    if not fit:
        return {"alpha_mean": measure.alpha_shift, "alpha_sd": 0.5, "b": DEFAULT_B,
                "gamma": 0.0, "calibrated": False, "gamma_identified": False}
    items = pd.DataFrame(fit["items"])
    fam = items[items["family"] == measure.family] if measure.family else items
    if fam.empty:
        fam = items
    scale = fit["scale"]
    alphas = fam["alpha"].to_numpy(float)
    drift = latest_cutpoint(fam, measure.as_of) if measure.alpha_mode == "latest" else None
    if drift is not None:
        return {
            "alpha_mean": float(drift["alpha"] + scale["mean"] + measure.alpha_shift),
            "alpha_sd": drift["sd"],
            "b": float(scale["sd"] / scale["k"]),
            "gamma": float(fit["gamma"]),
            "calibrated": True,
            "gamma_identified": bool(fit["gamma_identified"]),
            "alpha_mode": f"latest ({drift['latest_date']}, {drift['months']:.0f} months of drift)",
        }
    # Latent = alpha + lin + gamma*CP, with lin = score * sd / k + mean. Gamma was
    # estimated jointly with the cutpoints, so it enters separately through CP.
    return {
        "alpha_mean": float(alphas.mean() + scale["mean"] + measure.alpha_shift),
        "alpha_sd": float(max(alphas.std(), 0.1)) if len(alphas) > 1 else 0.5,
        "b": float(scale["sd"] / scale["k"]),
        "gamma": float(fit["gamma"]),
        "calibrated": True,
        "gamma_identified": bool(fit["gamma_identified"]),
    }


MIN_DRIFT_SD = 0.2
# AUDIT: support on a moving issue reverts toward its long-run (family) average
# with this half-life, so uncertainty stops growing instead of exploding.
DRIFT_HALF_LIFE_MONTHS = 18.0


def latest_cutpoint(fam: pd.DataFrame, as_of: str) -> dict | None:
    """Mean-reverting cutpoint: start at the most recent vote, revert toward the family mean.

    Ornstein-Uhlenbeck: after t months the mean is mu + (latest - mu) * exp(-k t)
    and the variance is s^2 (1 - exp(-2 k t)) / (2 k), with k = ln 2 / half-life and
    s the per-month volatility estimated from changes between successive votes.
    Needs at least three dated votes; otherwise returns None and the caller falls
    back to the family average.
    """
    if "date" not in fam:
        return None
    f = fam.assign(_d=pd.to_datetime(fam["date"], errors="coerce")).dropna(subset=["_d"])
    f = f.sort_values("_d")
    if len(f) < 3:
        return None
    gaps = f["_d"].diff().dt.days.iloc[1:].to_numpy() / 30.44
    steps = np.diff(f["alpha"].to_numpy(float))
    keep = gaps > 0.25
    if keep.sum() < 2:
        return None
    per_month = float(np.sqrt(np.mean(steps[keep] ** 2 / gaps[keep])))
    months = max((pd.Timestamp(as_of) - f["_d"].iloc[-1]).days / 30.44, 1.0)
    k = np.log(2) / DRIFT_HALF_LIFE_MONTHS
    mu, latest = float(f["alpha"].mean()), float(f["alpha"].iloc[-1])
    mean = mu + (latest - mu) * np.exp(-k * months)
    var = per_month ** 2 * (1 - np.exp(-2 * k * months)) / (2 * k)
    return {
        "alpha": float(mean),
        "sd": float(max(np.sqrt(var), MIN_DRIFT_SD)),
        "latest_date": f["_d"].iloc[-1].date().isoformat(),
        "months": months,
    }


def simulate(
    scores: pd.DataFrame,
    measure: Measure,
    president: str,
    calibration: dict | None = None,
    runs: int = 10000,
    seed: int = 0,
) -> dict:
    """Simulate a measure under a White House held by `president` ('D' or 'R')."""
    rng = np.random.default_rng(seed)
    p = measure_parameters(measure, calibration)
    theta = scores[measure.dimension].to_numpy(float)
    sd = scores[f"{measure.dimension}_sd"].to_numpy(float)
    caucus = scores["caucus"].to_numpy()
    cp = (caucus == president).astype(float)
    n = len(theta)
    caucuses = np.unique(caucus)
    yea_is_plus = measure.plus_side.lower() == "yea"

    # Ties go the White House's way (the Vice President votes).
    tie_passes = measure.president_position == "support"

    eps = rng.normal(0, 1, (runs, n)) * sd                      # once per run
    alpha = rng.normal(p["alpha_mean"], p["alpha_sd"], runs)[:, None]
    base_latent = alpha + p["b"] * (theta + eps) + p["gamma"] * cp

    alive = np.ones(runs, bool)
    results = {"stages": {}}
    pivot_counts = np.zeros(n)
    yea_record = None
    for stage in measure.stages:
        shock = np.zeros((runs, n))
        for c in caucuses:
            shock[:, caucus == c] = rng.normal(0, measure.tau, (runs, 1))
        latent = base_latent + shock + rng.normal(0, 1, (runs, n))
        plus = latent > 0
        yea = plus if yea_is_plus else ~plus
        present = rng.random((runs, n)) < ATTENDANCE
        yeas = (yea & present).sum(1)
        nays = (~yea & present).sum(1)
        ok = _passes(yeas, nays, stage.threshold, tie_passes)
        alive &= ok
        results["stages"][stage.name] = {
            "p_pass_cumulative": float(alive.mean()),
            "p_pass_if_reached": float(ok.mean()),
            "yeas_median": float(np.median(yeas)),
            "yeas_p10_p90": [float(np.percentile(yeas, 10)), float(np.percentile(yeas, 90))],
        }
        yea_record = (yea, present, latent)

    # Pivotal senator on the final stage: the member whose support is the marginal
    # vote needed under the last threshold, ranked by latent support.
    yea, present, latent = yea_record
    signed = np.where(present, latent if yea_is_plus else -latent, -np.inf)
    voting = present.sum(1)
    need = {"majority": voting // 2 + 1, "cloture": np.full(runs, 60),
            "two_thirds": np.ceil(2 * voting / 3).astype(int)}[measure.stages[-1].threshold]
    order = np.argsort(-signed, axis=1)
    pivot = order[np.arange(runs), np.clip(need - 1, 0, n - 1)]
    np.add.at(pivot_counts, pivot, 1)

    p_senate = float(alive.mean())
    out = {
        "measure": measure.name,
        "president": president,
        "runs": runs,
        "parameters": p,
        "p_passes_senate": p_senate,
        **results,
    }
    if measure.veto_possible and measure.president_position == "oppose":
        # Override vote: same senators, fresh noise, two-thirds of those voting.
        latent = base_latent + rng.normal(0, 1, (runs, n))
        plus = latent > 0
        yea = plus if yea_is_plus else ~plus
        present = rng.random((runs, n)) < ATTENDANCE
        ok = _passes((yea & present).sum(1), (~yea & present).sum(1), "two_thirds", False)
        p_senate_override = float((alive & ok).mean() / p_senate) if p_senate else 0.0
        p_both = p_senate * measure.house_pass_prob
        p_enacted = p_both * ((1 - P_VETO_IF_OPPOSED)
                              + P_VETO_IF_OPPOSED * p_senate_override * measure.house_override_prob)
        out.update({
            "p_passes_both_chambers": p_both,
            "p_veto_if_passed": P_VETO_IF_OPPOSED,
            "p_senate_override_if_passed": p_senate_override,
            "p_enacted": p_enacted,
        })
    else:
        out["p_enacted"] = p_senate * measure.house_pass_prob

    share = pivot_counts / runs
    top = np.argsort(-share)[:5]
    out["pivotal_senators"] = [
        {"name": scores["name"].iloc[i], "caucus": caucus[i], "share": round(float(share[i]), 3)}
        for i in top if share[i] > 0
    ]
    return out


def required_defectors(seats_president_party: int, chamber_size: int = 100) -> int:
    """Members of the President's party needed to reach two-thirds with full attendance."""
    need = math.ceil(2 * chamber_size / 3)
    other = chamber_size - seats_president_party
    return max(need - other, 0)
