"""Multi-cycle simulation: 120th (2027-28), 121st (2029-30), 122nd (2031-32) Congresses.

Each outer run:
  1. 120th Congress: the projected roster; Republican White House.
  2. 2028: President drawn (or fixed by scenario) with an environment that starts
     from the estimated 2026 environment and reverts toward neutral. Every Class 3
     seat holds an election: the incumbent may retire (age-based), then the race is
     drawn from state lean, environment and incumbency.
  3. 2030: midterm environment penalises the President's party; Class 1 seats vote.
  4. Each Congress: new senators are scored with the no-record rule (caucus median,
     pulled toward centre in split states); committees are re-projected from the
     previous Congress (departures leave, sides follow the majority, chairs go to
     the top remaining member) and vacancies are filled with unassigned senators.
  5. Each measure is simulated in each Congress with the vote model.

Senate control: 51 seats, or 50 plus the Vice President (the White House party).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from senate_sim import committees, config, elections
from senate_sim.policy import base
from senate_sim.simulation import Measure, simulate

CONGRESSES = [
    {"congress": 120, "start_year": 2027, "as_of": "2027-06-01"},
    {"congress": 121, "start_year": 2029, "as_of": "2029-06-01"},
    {"congress": 122, "start_year": 2031, "as_of": "2031-06-01"},
]
ELECTIONS = [  # (year, class up, Congress that results)
    (2028, 3, 121),
    (2030, 1, 122),
]
MAX_COMMITTEES = 3     # AUDIT: seats per new senator when filling vacancies
MAX_SUPER_A = 1        # AUDIT
DEFAULT_AGE = 50       # incoming senators with no birthday on file

ROSTER_COLUMNS = ["bioguide_id", "name", "state", "caucus", "senate_class", "birth_year",
                  "nominate_dim1", "nominate_dim2", "score_chamber", "incoming"]


@dataclass
class Scenario:
    president_2028: str = "sim"         # "sim", "D" or "R"
    env_2028_mean: float | None = None  # None: ENV_RETENTION * estimated 2026 environment
    runs: int = 300
    inner_runs: int = 200
    seed: int = 0


def environment_2026(baseline: pd.DataFrame, lean: dict) -> tuple[float, float, int]:
    """Estimate the 2026 environment from who holds each seat that was up in 2026.

    Seats up: Class 2, plus incoming Class 3 senators (special elections). A sitting
    senator in such a seat was re-elected as incumbent; an incoming one won an open
    seat or beat the incumbent (treated as open, which understates incumbency).
    """
    up = baseline[(baseline["senate_class"] == 2) | (baseline["incoming"] & (baseline["senate_class"] == 3))]
    seats = pd.DataFrame({
        "state": up["state"],
        "winner": up["caucus"].where(up["caucus"].isin(["D", "R"]), "D"),
        "incumbent_party": np.where(up["incoming"], None, up["caucus"]),
    })
    env, se = elections.estimate_environment(seats, lean)
    return env, se, len(seats)


def control(roster: pd.DataFrame, president: str) -> str:
    d = int((roster["caucus"] == "D").sum())
    if d > 50 or (d == 50 and president == "D"):
        return "D"
    return "R"


def hold_elections(rng, roster: pd.DataFrame, seat_class: int, year: int, env: float,
                   lean: dict) -> pd.DataFrame:
    rows = []
    for _, s in roster.iterrows():
        if s["senate_class"] != seat_class:
            rows.append({**s.to_dict(), "incoming": False})
            continue
        age = year - (s["birth_year"] if pd.notna(s["birth_year"]) else year - DEFAULT_AGE)
        retires = rng.random() < elections.retire_prob(age)
        holder = s["caucus"] if s["caucus"] in ("D", "R") else "D"
        winner = elections.senate_race(rng, lean.get(s["state"], 0.0), env, None if retires else holder)
        if not retires and winner == holder:
            rows.append({**s.to_dict(), "incoming": False})
            continue
        rows.append({
            "bioguide_id": f"SIM{year}-{s['state']}-{seat_class}", "name": f"New {winner} ({s['state']}, {year})",
            "state": s["state"], "caucus": winner, "senate_class": seat_class,
            "birth_year": year - DEFAULT_AGE, "nominate_dim1": np.nan, "nominate_dim2": np.nan,
            "score_chamber": None, "incoming": True,
        })
    return pd.DataFrame(rows, columns=ROSTER_COLUMNS)


def assignments_to_membership(assignments: pd.DataFrame) -> pd.DataFrame:
    """Turn projected seats back into a membership table for the next projection."""
    m = assignments[assignments["status"] == "member"].copy()
    m["rank"] = m["side_rank"]
    m["title"] = m["title"].fillna("")
    return m[["committee_id", "committee_name", "tier", "bioguide_id", "member_name", "side", "rank", "title"]]


def fill_vacancies(rng, assignments: pd.DataFrame, roster: pd.DataFrame, majority: str) -> pd.DataFrame:
    """Seat unassigned senators in open seats: fewest committees first, random among ties."""
    a = assignments.copy()
    seated = a[a["status"] == "member"]
    load = seated.groupby("bioguide_id").size().to_dict()
    super_a = seated[seated["tier"] == "Super A"].groupby("bioguide_id").size().to_dict()
    on = set(zip(seated["committee_id"], seated["bioguide_id"]))
    names = roster.set_index("bioguide_id")["name"].to_dict()
    caucus = roster.set_index("bioguide_id")["caucus"].to_dict()
    for i in a.index[a["status"] == "vacancy"]:
        cid, side, tier = a.at[i, "committee_id"], a.at[i, "side"], a.at[i, "tier"]
        want = majority if side == "majority" else ("R" if majority == "D" else "D")
        pool = [b for b, c in caucus.items()
                if c == want and (cid, b) not in on and load.get(b, 0) < MAX_COMMITTEES
                and not (tier == "Super A" and super_a.get(b, 0) >= MAX_SUPER_A)]
        if not pool:
            continue
        lowest = min(load.get(b, 0) for b in pool)
        pick = rng.choice([b for b in pool if load.get(b, 0) == lowest])
        a.loc[i, ["bioguide_id", "member_name", "caucus", "status"]] = [pick, names.get(pick, pick), want, "member"]
        load[pick] = load.get(pick, 0) + 1
        if tier == "Super A":
            super_a[pick] = super_a.get(pick, 0) + 1
        on.add((cid, pick))
    return a


def leadership_of(assignments: pd.DataFrame, committee_ids: list[str]) -> dict:
    out = {}
    for cid in committee_ids:
        rows = assignments[(assignments["committee_id"] == cid) & (assignments["title"] != "")]
        for _, r in rows.iterrows():
            key = "chair" if r["side"] == "majority" else "ranking"
            out[f"{cid}_{key}"] = r["member_name"]
    return out


def run(baseline: pd.DataFrame, birth_years: dict, lean: dict, assignments_120: pd.DataFrame,
        sectors: list[tuple], scenario: Scenario, donor_adjustment=None) -> dict:
    """Simulate every sector against the same elections and committees.

    sectors: (module, calibration, measures) tuples. Measure keys in the output
    are "<module>:<measure>".
    """
    rng = np.random.default_rng(scenario.seed)
    committee_ids = sorted({c for module, _, _ in sectors for c in (module.committees or [])})
    env26, env26_se, n26 = environment_2026(baseline, lean)
    env28_mean = scenario.env_2028_mean if scenario.env_2028_mean is not None else elections.ENV_RETENTION * env26

    roster120 = baseline.assign(birth_year=baseline["bioguide_id"].map(birth_years))
    roster120 = roster120.reindex(columns=ROSTER_COLUMNS)
    roster120["incoming"] = roster120["incoming"].fillna(False).astype(bool)
    membership120 = assignments_to_membership(assignments_120)

    congress_rows, measure_rows, leader_rows = [], [], []
    for r in range(scenario.runs):
        want = None if scenario.president_2028 == "sim" else scenario.president_2028
        pres28, national28, d_ev = elections.draw_president(rng, env28_mean, lean, want)
        env28 = national28 + rng.normal(0, elections.SENATE_ENV_NOISE)
        midterm_mean = -elections.MIDTERM_PENALTY if pres28 == "D" else elections.MIDTERM_PENALTY
        env30 = rng.normal(midterm_mean, elections.MIDTERM_SD)

        rosters = {120: roster120}
        rosters[121] = hold_elections(rng, roster120, 3, 2028, env28, lean)
        rosters[122] = hold_elections(rng, rosters[121], 1, 2030, env30, lean)
        presidents = {120: "R", 121: pres28, 122: pres28}

        membership = membership120
        for c in CONGRESSES:
            n = c["congress"]
            roster, president = rosters[n], presidents[n]
            majority = control(roster, president)
            named = roster.assign(name=roster["name"].fillna(roster["bioguide_id"]))

            assign, _ = committees.project(membership, roster[["bioguide_id", "caucus"]], new_majority=majority)
            assign = fill_vacancies(rng, assign, roster, majority)
            membership = assignments_to_membership(assign)
            leader_rows.append({"run": r, "congress": n, **leadership_of(assign, committee_ids)})

            d_seats = int((roster["caucus"] == "D").sum())
            congress_rows.append({
                "run": r, "congress": n, "president": president, "senate_control": majority,
                "d_seats": d_seats, "new_senators": int(roster["incoming"].sum()) if n > 120 else 0,
                "national_2028": national28, "d_electoral_votes": d_ev, "env_2030": env30,
            })
            for module, calibration, measures in sectors:
                scores = base.score(named, module, calibration, strict_overrides=False,
                                    donor_adjustment=donor_adjustment)
                scores = scores.merge(roster[["bioguide_id"]], on="bioguide_id")
                for key, m in measures.items():
                    res = simulate(scores, replace(m, as_of=c["as_of"]), president, calibration,
                                   runs=scenario.inner_runs, seed=int(rng.integers(1 << 31)))
                    last = list(res["stages"].values())[-1]
                    measure_rows.append({"run": r, "congress": n, "module": module.name,
                                         "measure": f"{module.name}:{key}",
                                         "p_passes_senate": res["p_passes_senate"], "p_enacted": res["p_enacted"],
                                         "yeas_median": last["yeas_median"]})

    return {
        "environment_2026": {"estimate": env26, "se": env26_se, "seats": n26, "env_2028_mean": env28_mean},
        "congress": pd.DataFrame(congress_rows),
        "measures": pd.DataFrame(measure_rows),
        "leadership": pd.DataFrame(leader_rows),
    }


def summarize(result: dict) -> dict[str, pd.DataFrame]:
    c, m, l = result["congress"], result["measures"], result["leadership"]
    congress = c.groupby("congress").agg(
        p_d_white_house=("president", lambda s: (s == "D").mean()),
        p_d_senate=("senate_control", lambda s: (s == "D").mean()),
        d_seats_mean=("d_seats", "mean"),
        d_seats_p10=("d_seats", lambda s: s.quantile(0.1)),
        d_seats_p90=("d_seats", lambda s: s.quantile(0.9)),
        new_senators_mean=("new_senators", "mean"),
    ).reset_index()
    by_wh = m.merge(c[["run", "congress", "president"]], on=["run", "congress"])
    if "module" not in by_wh:
        by_wh["module"] = by_wh["measure"].str.split(":").str[0]
    measures = by_wh.groupby(["module", "measure", "congress"]).agg(
        p_passes_senate=("p_passes_senate", "mean"), p_enacted=("p_enacted", "mean"),
        yeas_median=("yeas_median", "median")).reset_index()
    measures_wh = by_wh.groupby(["module", "measure", "congress", "president"]).agg(
        p_passes_senate=("p_passes_senate", "mean"), p_enacted=("p_enacted", "mean"),
        yeas_median=("yeas_median", "median"), runs=("run", "nunique")).reset_index()
    leaders = []
    for col in [x for x in l.columns if x not in ("run", "congress")]:
        top = l.groupby("congress")[col].agg(lambda s: s.value_counts(normalize=True).head(3).round(2).to_dict())
        for n, d in top.items():
            leaders.append({"congress": n, "post": col, "top_holders": d})
    return {"congress": congress, "measures": measures, "measures_by_white_house": measures_wh,
            "leadership": pd.DataFrame(leaders)}
