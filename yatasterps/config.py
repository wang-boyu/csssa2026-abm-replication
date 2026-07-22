from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class WorldBounds:
    min_x: int
    max_x: int
    min_y: int
    max_y: int

    @property
    def width(self) -> int:
        return self.max_x - self.min_x + 1

    @property
    def height(self) -> int:
        return self.max_y - self.min_y + 1


@dataclass(frozen=True)
class ParameterSpec:
    minimum: int
    maximum: int
    default: int
    step: int = 1


WORLD_BOUNDS: Final = WorldBounds(min_x=-16, max_x=16, min_y=-20, max_y=20)

DEFAULT_YOUTH_COUNT: Final[int] = 150
DEFAULT_MAX_TICKS: Final[int] = 1800
DEFAULT_SEED: Final[int] = 42
PATCH_OPPORTUNITY_MIN: Final[float] = 0.01
PATCH_OPPORTUNITY_MAX: Final[float] = 0.99
YOUTH_FACTOR_MIN: Final[float] = 0.01
YOUTH_FACTOR_MAX: Final[float] = 0.99
INDIVIDUAL_FACTOR_STDDEV: Final[float] = 0.02
TALLY_INCREMENT: Final[float] = 0.10
YOUTH_TURN_PROBABILITY: Final[float] = 0.10
PROBABILITY_DELTA: Final[float] = 0.001
FAMILY_INFLUENCE_UPPER_GATE: Final[float] = 0.980
FAMILY_INFLUENCE_LOWER_GATE: Final[float] = 0.020

SCHOOL_HOURS: Final[int] = 6
AFTER_SCHOOL_HOURS: Final[int] = 5
EVENING_HOURS: Final[int] = 4

PARAMETER_SPECS: Final[dict[str, ParameterSpec]] = {
    "risk_level": ParameterSpec(minimum=1, maximum=99, default=99),
    "promotive_level": ParameterSpec(minimum=1, maximum=99, default=99),
    "schools_risk": ParameterSpec(minimum=1, maximum=99, default=99),
    "schools_promotive": ParameterSpec(minimum=1, maximum=99, default=99),
    "neighborhood_risk": ParameterSpec(minimum=1, maximum=99, default=99),
    "neighborhood_promotive": ParameterSpec(minimum=1, maximum=99, default=99),
}

REGION_LAYER_NAME: Final[str] = "region_band"
RISK_OPP_LAYER_NAME: Final[str] = "risk_opp"
PRO_OPP_LAYER_NAME: Final[str] = "pro_opp"

REGION_CODES: Final[dict[str, int]] = {
    "home": 0,
    "neighborhood": 1,
    "school": 2,
}

REGION_COLORS: Final[dict[str, str]] = {
    "home": "#2b6cb0",
    "neighborhood": "#5f8f3d",
    "school": "#8c6239",
}

YOUTH_COLORS: Final[dict[str, str]] = {
    "setup": "#808080",
    "antisocial": "#d62828",
    "prosocial": "#32cd32",
}

HOME_Y_MIN: Final[int] = WORLD_BOUNDS.min_y
HOME_Y_MAX: Final[int] = -16
NEIGHBORHOOD_Y_MIN: Final[int] = -15
NEIGHBORHOOD_Y_MAX: Final[int] = 15
SCHOOL_Y_MIN: Final[int] = 16
SCHOOL_Y_MAX: Final[int] = WORLD_BOUNDS.max_y

PIPELINE_STAGE_ORDER: Final[tuple[str, ...]] = (
    "school",
    "after_school",
    "evening",
    "step_day",
)


def world_dimensions() -> tuple[int, int]:
    return WORLD_BOUNDS.width, WORLD_BOUNDS.height


def netlogo_to_grid(x: int, y: int) -> tuple[int, int]:
    return x - WORLD_BOUNDS.min_x, y - WORLD_BOUNDS.min_y


def grid_to_netlogo(col: int, row: int) -> tuple[int, int]:
    return col + WORLD_BOUNDS.min_x, row + WORLD_BOUNDS.min_y
