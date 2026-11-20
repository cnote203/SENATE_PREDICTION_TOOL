"""Policy modules. Each module defines its dimensions; the shared engine scores them."""
from __future__ import annotations

import importlib

MODULE_NAMES = ["foreign_policy", "healthcare", "energy", "banking", "tech"]


def get(name: str):
    return importlib.import_module(f"senate_sim.policy.{name}").MODULE


def all_modules():
    return [get(n) for n in MODULE_NAMES]
