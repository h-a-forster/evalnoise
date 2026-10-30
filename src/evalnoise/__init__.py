"""Variance components of agent-eval scores, and how many tasks, repeats and runs you need."""

from evalnoise.components import Components, bootstrap, estimate
from evalnoise.data import DataError, load_trials, to_trials
from evalnoise.power import (
    Design,
    mde,
    naive_false_positive_rate,
    plan,
    power_at,
    resolve,
    tasks_needed,
)

__version__ = "0.1.0"

__all__ = [
    "Components",
    "DataError",
    "Design",
    "bootstrap",
    "estimate",
    "load_trials",
    "mde",
    "naive_false_positive_rate",
    "plan",
    "power_at",
    "resolve",
    "tasks_needed",
    "to_trials",
    "__version__",
]
