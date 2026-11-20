"""AI and technology module: AI regulation, platform accountability, antitrust.

No usable 119th Congress roll calls: the one recorded AI vote (stripping the
state-law moratorium from H.R.1) was 99-1, and kids' online safety and antitrust
bills moved by unanimous consent or not at all. All three dimensions use
starting formulas with wide uncertainty, plus sponsorship-based overrides.
Coalitions here cut across party: populist Republicans and progressive
Democrats both favour tougher rules on large platforms.
AUDIT: priors are hand-set.
"""
from __future__ import annotations

from senate_sim import config
from senate_sim.policy.base import Dimension, PolicyModule
from senate_sim.simulation import Measure, Stage

MEASURES = {
    "ai_safety_framework": Measure(
        "Federal AI safety and liability framework", "ai_regulation", None, "Yea",
        [Stage("cloture", "cloture"), Stage("passage", "majority")],
        president_position=None, veto_possible=False, tau=0.35,
        notes="No calibration votes: uses the starting formula.",
    ),
    "kids_online_safety": Measure(
        "Kids' online safety bill", "platform_accountability", None, "Yea",
        [Stage("cloture", "cloture"), Stage("passage", "majority")],
        president_position=None, veto_possible=False, tau=0.3,
    ),
    "tech_antitrust_bill": Measure(
        "Big Tech antitrust bill (self-preferencing ban)", "tech_antitrust", None, "Yea",
        [Stage("cloture", "cloture"), Stage("passage", "majority")],
        president_position=None, veto_possible=False, tau=0.35,
    ),
}

MODULE = PolicyModule(
    name="tech",
    label="AI & tech",
    measures=MEASURES,
    committees=["SSCM", "SSJU"],
    dimensions=[
        Dimension(
            "ai_regulation",
            label="AI regulation", short="AI", low_tag="LIGHT", high_tag="BINDING",
            low="light-touch federal rules, pre-empts state AI laws",
            high="binding safety, liability and transparency rules for AI",
            formula=lambda d1, d2: 0.2 - 1.0 * d1,
            calibrate=False, prior_sd=0.7,
        ),
        Dimension(
            "platform_accountability",
            label="Platform accountability", short="230", low_tag="PROTECT", high_tag="ACCOUNT",
            low="protects platforms' liability shield and design choices",
            high="kids' online safety duties, Section 230 reform",
            formula=lambda d1, d2: 0.8 - 0.3 * d1,
            calibrate=False, prior_sd=0.7,
        ),
        Dimension(
            "tech_antitrust",
            label="Tech antitrust", short="ANTI", low_tag="OPPOSE", high_tag="BREAK UP",
            low="opposes new competition rules for large platforms",
            high="bans self-preferencing, supports breaking up dominant platforms",
            formula=lambda d1, d2: 0.2 - 0.8 * d1 + 1.5 * (d1 - 0.1) ** 2,
            calibrate=False, prior_sd=0.7,
        ),
    ],
    override_path=config.PROJECT_ROOT / "data" / "manual" / "overrides_tech.csv",
    calibration_path=config.PROJECT_ROOT / "data" / "calibration" / "tech.json",
)
