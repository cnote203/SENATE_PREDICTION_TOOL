"""Foreign policy module: four dimensions on a -2..+2 scale.

DW-NOMINATE dim1 runs from liberal (about -1) to conservative (about +1).
dim2 is used lightly: in recent Congresses it is noisy and carries little
stable foreign policy meaning.

The formulas are starting points, not findings. They encode three patterns:
- defence spending and China hawkishness rise with conservatism;
- interventionism peaks near the centre-right and falls off at both ends
  (the progressive left and the restraint right both resist commitments);
- arms-sale oversight is strongest on the left and at the libertarian right,
  weakest among mainstream Republicans.
Senators who break from these patterns go in the override file.
AUDIT: coefficients are hand-set; calibrate against 119th Congress roll calls.
"""
from __future__ import annotations

import numpy as np

from senate_sim import config
from senate_sim.policy.base import Dimension, PolicyModule
from senate_sim.simulation import Measure, Stage


def _nato(d1, d2):
    return 1.2 - 3.0 * (d1 - 0.1) ** 2 + 0.2 * d2


def _defense(d1, d2):
    # Prior only. FY26 NDAA votes show Nays at both ends (progressives and Paul/Lee),
    # so the calibrated fit is expected to bend down at the far right.
    return 0.4 + 1.6 * d1


def _arms_oversight(d1, d2):
    return -0.5 - 1.2 * d1 + 2.0 * (d1 - 0.1) ** 2


def _china(d1, d2):
    return 0.8 + 0.9 * d1


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


MODULE = PolicyModule(
    name="foreign_policy",
    label="Foreign policy",
    measures=PRESETS,
    committees=["SSFR", "SSAS", "SSAP", "SLIN"],
    dimensions=[
        Dimension(
            "nato_interventionism",
            label="Interventionism", short="INTV", low_tag="RESTRAINT", high_tag="HAWKISH",
            low="restraint: limits war powers and troop commitments, cuts Ukraine and NATO aid",
            high="hawkish: backs alliance commitments, military aid, and use of force",
            formula=_nato,
        ),
        Dimension(
            "defense_budget",
            label="Defense budget", short="DEF$", low_tag="CUT", high_tag="INCREASE",
            low="votes for cuts or flat budgets, opposes NDAA toplines",
            high="votes for increases above the President's request",
            formula=_defense,
        ),
        Dimension(
            "arms_sales_oversight",
            label="Arms-sale oversight", short="ARMS", low_tag="DEFER", high_tag="BLOCK",
            low="defers to the executive, opposes disapproval resolutions",
            high="supports disapproval resolutions and conditions on sales",
            formula=_arms_oversight,
        ),
        Dimension(
            "china_decoupling",
            label="China decoupling", short="PRC", low_tag="ENGAGE", high_tag="DECOUPLE",
            low="favours engagement and trade, opposes export controls and investment limits",
            high="backs tariffs, export controls, investment screening, Taiwan arms sales",
            formula=_china,
            # No clean China roll calls in the 119th Senate: the outbound-investment and
            # biotech provisions passed by voice vote, and tariff-emergency votes measure
            # deference to the President, not China policy. Keep the prior, widen its SD.
            calibrate=False,
            prior_sd=0.6,
        ),
    ],
    override_path=config.PROJECT_ROOT / "data" / "manual" / "overrides_foreign_policy.csv",
    calibration_path=config.PROJECT_ROOT / "data" / "calibration" / "foreign_policy.json",
)
