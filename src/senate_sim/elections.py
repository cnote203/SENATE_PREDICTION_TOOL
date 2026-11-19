"""Senate and presidential election draws for the multi-cycle simulation.

State partisanship is each state's 2024 two-party presidential margin relative to
the nation (data: tonmcg/US_County_Level_Election_Results_08-24, county results
aggregated to states). Margins are Democratic minus Republican, in points.

Senate race (Democratic margin in state s, cycle c):
    lean_s + env_c + incumbency + N(0, RACE_SD)
Presidential (2028):
    state margin = lean_s + national + N(0, STATE_SD_PRES); electoral votes winner-take-all

The 2026 environment is estimated from the 2026 Senate results (which party won
each seat up that year), by maximum likelihood under the same race model. Later
environments start from it and revert toward neutral.

Every constant marked AUDIT is a judgment call from the general election-forecasting
literature, not fitted here.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.stats import norm

from senate_sim import config

PRES_2024_URL = ("https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-24/"
                 "master/2024_US_County_Level_Presidential_Results.csv")

RACE_SD = 6.0          # AUDIT: race-level error, points
INC_ADV = 3.0          # AUDIT: incumbent's advantage, points
STATE_SD_PRES = 2.5    # AUDIT: state deviation from national swing in a presidential race
PRES_SD = 5.0          # AUDIT: uncertainty of the 2028 national popular-vote margin
SENATE_ENV_NOISE = 2.0  # AUDIT: Senate environment vs presidential margin in the same year
ENV_RETENTION = 0.5    # AUDIT: share of the 2026 environment carried into 2028
MIDTERM_PENALTY = 4.0  # AUDIT: average midterm loss for the President's party, points
MIDTERM_SD = 4.0       # AUDIT

# Electoral votes, 2024-2028 apportionment (2020 census). Maine and Nebraska
# district splits are ignored (winner-take-all approximation).
ELECTORAL_VOTES = {
    "AL": 9, "AK": 3, "AZ": 11, "AR": 6, "CA": 54, "CO": 10, "CT": 7, "DE": 3, "DC": 3, "FL": 30,
    "GA": 16, "HI": 4, "ID": 4, "IL": 19, "IN": 11, "IA": 6, "KS": 6, "KY": 8, "LA": 8, "ME": 4,
    "MD": 10, "MA": 11, "MI": 15, "MN": 10, "MS": 6, "MO": 10, "MT": 4, "NE": 5, "NV": 6, "NH": 4,
    "NJ": 14, "NM": 5, "NY": 28, "NC": 16, "ND": 3, "OH": 17, "OK": 7, "OR": 8, "PA": 19, "RI": 4,
    "SC": 9, "SD": 3, "TN": 11, "TX": 40, "UT": 6, "VT": 3, "VA": 13, "WA": 12, "WV": 4, "WI": 10,
    "WY": 3,
}


def state_lean(raw_csv: bytes) -> pd.DataFrame:
    """Aggregate county results to states: margin and lean relative to the nation."""
    d = pd.read_csv(io.BytesIO(raw_csv))
    s = d.groupby("state_name")[["votes_dem", "votes_gop"]].sum()
    s["margin"] = (s["votes_dem"] - s["votes_gop"]) / (s["votes_dem"] + s["votes_gop"]) * 100
    national = (s["votes_dem"].sum() - s["votes_gop"].sum()) / (s["votes_dem"].sum() + s["votes_gop"].sum()) * 100
    codes = {**config.STATE_CODES, "District of Columbia": "DC"}
    s = s.reset_index()
    s["state"] = s["state_name"].map(codes)
    s["lean"] = s["margin"] - national
    s["national_2024"] = national
    return s.dropna(subset=["state"])[["state", "margin", "lean", "national_2024"]]


def race_mean(lean, env, incumbent_party):
    inc = np.where(incumbent_party == "D", INC_ADV, np.where(incumbent_party == "R", -INC_ADV, 0.0))
    return lean + env + inc


def estimate_environment(seats: pd.DataFrame, lean: dict) -> tuple[float, float]:
    """MLE of a cycle's national environment from who won each seat.

    seats: state, winner ('D'/'R'), incumbent_party ('D'/'R'/None for open seats)
    Returns (environment, standard error), Democratic margin in points.
    """
    l = seats["state"].map(lean).to_numpy(float)
    inc = seats["incumbent_party"].fillna("").to_numpy()
    q = np.where(seats["winner"] == "D", 1.0, -1.0)

    def nll(env):
        return -norm.logcdf(q * race_mean(l, env, inc) / RACE_SD).sum()

    res = minimize_scalar(nll, bounds=(-40, 40), method="bounded")
    h = 1e-3
    curv = (nll(res.x + h) - 2 * nll(res.x) + nll(res.x - h)) / h ** 2
    return float(res.x), float(1 / np.sqrt(curv)) if curv > 0 else float("nan")


def retire_prob(age: float) -> float:
    """AUDIT: retirement probability for a senator whose seat is up, by age at election."""
    if age >= 80:
        return 0.50
    if age >= 75:
        return 0.30
    if age >= 70:
        return 0.15
    if age >= 60:
        return 0.08
    return 0.04


def draw_president(rng, national_mean: float, lean: dict, want: str | None = None, max_tries: int = 500):
    """Draw a 2028 national margin and Electoral College winner.

    want='D' or 'R' conditions on that winner by rejection sampling, so the
    environment that comes with it stays consistent with the result.
    """
    states = list(ELECTORAL_VOTES)
    ev = np.array([ELECTORAL_VOTES[s] for s in states])
    l = np.array([lean.get(s, 0.0) for s in states])
    for _ in range(max_tries):
        national = rng.normal(national_mean, PRES_SD)
        margins = l + national + rng.normal(0, STATE_SD_PRES, len(states))
        d_ev = int(ev[margins > 0].sum())
        winner = "D" if d_ev >= 270 else "R"  # a 269-269 tie goes to the House: assumed R
        if want is None or winner == want:
            return winner, float(national), d_ev
    raise RuntimeError(f"Could not draw a {want} presidential win; check the environment settings.")


def senate_race(rng, lean_s: float, env: float, incumbent_party: str | None) -> str:
    margin = race_mean(np.array([lean_s]), env, np.array([incumbent_party or ""]))[0] + rng.normal(0, RACE_SD)
    return "D" if margin > 0 else "R"
