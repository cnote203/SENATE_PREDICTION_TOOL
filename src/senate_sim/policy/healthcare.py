"""Healthcare module: coverage, drug prices, public health.

Only coverage_expansion has clean 119th Congress roll calls (the December 2025
ACA credit votes and H.R.1). The other two dimensions keep their starting
formulas with wide uncertainty. AUDIT: coefficients are hand-set priors.
"""
from __future__ import annotations

from senate_sim import config
from senate_sim.policy.base import Dimension, PolicyModule
from senate_sim.simulation import Measure, Stage

MEASURES = {
    "aca_credit_extension": Measure(
        "Extend enhanced ACA premium tax credits", "coverage_expansion", "aca_credits", "Yea",
        [Stage("cloture", "cloture"), Stage("passage", "majority")],
        president_position={"R": "oppose", "D": "support"}, veto_possible=True, tau=0.25,
        house_pass_prob=0.5,
        notes="Ordinary bill: needs 60 for cloture. Four Republicans backed the December 2025 version.",
    ),
    "medicaid_cuts_reconciliation": Measure(
        "Reconciliation bill with Medicaid cuts", "coverage_expansion", "reconciliation", "Nay",
        [Stage("passage", "majority")],
        president_position={"R": "support", "D": "oppose"}, veto_possible=True, tau=0.2,
        house_pass_prob=0.6,
        notes="Budget reconciliation: simple majority, no filibuster. Yea is a vote for the cuts.",
    ),
    "drug_price_negotiation": Measure(
        "Expand Medicare drug price negotiation", "drug_price_controls", None, "Yea",
        [Stage("cloture", "cloture"), Stage("passage", "majority")],
        president_position=None, veto_possible=False, tau=0.3,
        notes="No calibration votes: uses the starting formula.",
    ),
}

MODULE = PolicyModule(
    name="healthcare",
    label="Healthcare",
    measures=MEASURES,
    committees=["SSHR", "SSFI", "SSAP"],
    dimensions=[
        Dimension(
            "coverage_expansion",
            label="Coverage expansion", short="COV", low_tag="CUT", high_tag="EXPAND",
            low="cuts Medicaid and ACA subsidies, favours HSAs and private alternatives",
            high="extends ACA credits, protects and expands Medicaid",
            formula=lambda d1, d2: -0.2 - 2.2 * d1,
        ),
        Dimension(
            "drug_price_controls",
            label="Drug price controls", short="RX", low_tag="MARKET", high_tag="CONTROL",
            low="market pricing, opposes negotiation and price caps",
            high="expands Medicare negotiation, caps prices",
            formula=lambda d1, d2: -0.1 - 1.6 * d1,
            calibrate=False, prior_sd=0.6,
        ),
        Dimension(
            "public_health_funding",
            label="Public health funding", short="NIH", low_tag="CUT", high_tag="FUND",
            low="cuts NIH, CDC and global health funding and authority",
            high="expands NIH, CDC and public health funding",
            formula=lambda d1, d2: 0.1 - 1.6 * d1,
            calibrate=False, prior_sd=0.6,
        ),
    ],
    override_path=config.PROJECT_ROOT / "data" / "manual" / "overrides_healthcare.csv",
    calibration_path=config.PROJECT_ROOT / "data" / "calibration" / "healthcare.json",
)
