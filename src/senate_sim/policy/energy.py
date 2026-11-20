"""Energy module: clean energy, fossil production, permitting.

clean_energy is calibrated on the 2025 Congressional Review Act votes (methane
fee, California vehicle waivers). AUDIT: priors are hand-set.
"""
from __future__ import annotations

from senate_sim import config
from senate_sim.policy.base import Dimension, PolicyModule
from senate_sim.simulation import Measure, Stage

MEASURES = {
    "climate_rule_repeal_cra": Measure(
        "CRA resolution repealing a climate or emissions rule", "clean_energy", "california_waivers", "Nay",
        [Stage("passage", "majority")],
        president_position={"R": "support", "D": "oppose"}, veto_possible=True, tau=0.2,
        house_pass_prob=0.6,
        notes="Congressional Review Act: simple majority. Yea is a vote to repeal the rule.",
    ),
    "clean_energy_credit_restoration": Measure(
        "Restore clean-energy tax credits", "clean_energy", None, "Yea",
        [Stage("cloture", "cloture"), Stage("passage", "majority")],
        president_position={"R": "oppose", "D": "support"}, veto_possible=True, tau=0.25,
        house_pass_prob=0.4,
    ),
    "permitting_reform": Measure(
        "Bipartisan permitting reform bill", "permitting_reform", None, "Yea",
        [Stage("cloture", "cloture"), Stage("passage", "majority")],
        president_position=None, veto_possible=False, tau=0.3,
        notes="No calibration votes: uses the starting formula.",
    ),
}

MODULE = PolicyModule(
    name="energy",
    label="Energy",
    measures=MEASURES,
    committees=["SSEG", "SSEV", "SSFI"],
    dimensions=[
        Dimension(
            "clean_energy",
            label="Clean energy", short="CLN", low_tag="FOSSIL", high_tag="CLEAN",
            low="repeals emissions rules and clean-energy incentives",
            high="defends emissions rules and clean-energy credits",
            formula=lambda d1, d2: -0.1 - 2.0 * d1,
        ),
        Dimension(
            "fossil_production",
            label="Fossil production", short="O&G", low_tag="RESTRICT", high_tag="EXPAND",
            low="restricts leasing, drilling and LNG exports",
            high="expands federal leasing, drilling and LNG exports",
            formula=lambda d1, d2: 0.2 + 1.8 * d1,
            calibrate=False, prior_sd=0.6,
        ),
        Dimension(
            "permitting_reform",
            label="Permitting reform", short="PRMT", low_tag="REVIEW", high_tag="SPEED",
            low="keeps full environmental review and litigation windows",
            high="shortens reviews and litigation to speed energy and transmission projects",
            formula=lambda d1, d2: 0.6 - 2.0 * (d1 - 0.15) ** 2,
            calibrate=False, prior_sd=0.7,
        ),
    ],
    override_path=config.PROJECT_ROOT / "data" / "manual" / "overrides_energy.csv",
    calibration_path=config.PROJECT_ROOT / "data" / "calibration" / "energy.json",
)
