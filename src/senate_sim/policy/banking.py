"""Banking module: consumer finance, crypto, bank regulation.

consumer_finance_regulation is calibrated on the 2025 CFPB CRA votes;
crypto_support on the GENIUS Act (S.1582) and CLARITY Act (H.R. 3633) votes.
AUDIT: priors are hand-set.
"""
from __future__ import annotations

from senate_sim import config
from senate_sim.policy.base import Dimension, PolicyModule
from senate_sim.simulation import Measure, Stage

MEASURES = {
    "cfpb_rule_repeal_cra": Measure(
        "CRA resolution repealing a CFPB rule", "consumer_finance_regulation", "cfpb_cra", "Nay",
        [Stage("passage", "majority")],
        president_position={"R": "support", "D": "oppose"}, veto_possible=True, tau=0.2,
        house_pass_prob=0.6,
        notes="Congressional Review Act: simple majority. Yea is a vote to repeal the rule.",
    ),
    "crypto_market_structure": Measure(
        "Crypto market structure bill (CLARITY-style)", "crypto_support", "clarity", "Yea",
        [Stage("cloture", "cloture"), Stage("passage", "majority")],
        president_position={"R": "support", "D": None}, veto_possible=False, tau=0.35,
        notes="Ethics provisions on officials' crypto holdings decided the 2026 vote.",
    ),
    "stablecoin_rules": Measure(
        "Stablecoin regulation bill (GENIUS-style)", "crypto_support", "genius", "Yea",
        [Stage("cloture", "cloture"), Stage("passage", "majority")],
        president_position={"R": "support", "D": None}, veto_possible=False, tau=0.3,
    ),
}

MODULE = PolicyModule(
    name="banking",
    label="Banking",
    measures=MEASURES,
    committees=["SSBK", "SSAF", "SSFI"],
    dimensions=[
        Dimension(
            "consumer_finance_regulation",
            label="Consumer finance rules", short="CFPB", low_tag="REPEAL", high_tag="PROTECT",
            low="repeals CFPB rules and narrows the bureau",
            high="defends and strengthens CFPB consumer protections",
            formula=lambda d1, d2: -0.1 - 2.0 * d1,
        ),
        Dimension(
            "crypto_support",
            label="Crypto support", short="BTC", low_tag="SKEPTIC", high_tag="PRO",
            low="opposes crypto frameworks, favours strict limits",
            high="backs stablecoin and market-structure frameworks",
            formula=lambda d1, d2: 0.6 + 1.0 * d1,
        ),
        Dimension(
            "bank_regulation",
            label="Bank regulation", short="BANK", low_tag="LOOSEN", high_tag="TIGHTEN",
            low="eases capital, stress-test and merger rules",
            high="tightens capital rules and big-bank oversight",
            formula=lambda d1, d2: -0.2 - 1.8 * d1,
            calibrate=False, prior_sd=0.6,
        ),
    ],
    override_path=config.PROJECT_ROOT / "data" / "manual" / "overrides_banking.csv",
    calibration_path=config.PROJECT_ROOT / "data" / "calibration" / "banking.json",
)
