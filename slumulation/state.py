from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import TypeAlias

from .constants import (
    CENTRAL_WARD,
    PERIPHERAL_WARDS,
    WARD_COORDINATE_RANGES,
    WORLD_BOUNDS,
    WORLD_HEIGHT,
    WORLD_PATCH_COUNT,
    WORLD_WIDTH,
    WORLD_X_MAX,
    WORLD_X_MIN,
    WORLD_Y_MAX,
    WORLD_Y_MIN,
)

Coordinate: TypeAlias = tuple[int, int]


@dataclass(slots=True)
class PatchState:
    x: int
    y: int
    ward: int
    rent: float = 0.0
    rent_payable: float = 0.0
    occupied: bool = False
    available: bool = True
    num_occupants: int = 0
    num_units: int = 1
    slum: bool = False
    slum_occupants: int = 0
    resicat: int = 0

    @property
    def coordinate(self) -> Coordinate:
        return (self.x, self.y)

    @property
    def central(self) -> bool:
        return is_central_ward(self.ward)

    @property
    def peripheral(self) -> bool:
        return is_peripheral_ward(self.ward)

    @property
    def is_central(self) -> bool:
        return self.central

    @property
    def is_peripheral(self) -> bool:
        return self.peripheral


LandState: TypeAlias = PatchState


@dataclass(slots=True)
class HouseholdState:
    x: int
    y: int
    income_class: str | None = None
    income: float = 0.0
    informal: bool = False
    searching: bool = False
    willing: bool = False
    class_updated: bool = False
    old: int = 0
    stay: int = 0
    num_houses: int = 0
    xcor: float | None = None
    ycor: float | None = None
    heading: float = 0.0

    def __post_init__(self) -> None:
        if self.xcor is None:
            self.xcor = float(self.x)
        if self.ycor is None:
            self.ycor = float(self.y)
        self.heading %= 360.0

    @property
    def coordinate(self) -> Coordinate:
        return (self.x, self.y)


@dataclass(slots=True)
class DeveloperState:
    x: int
    y: int
    no_role: bool = False

    @property
    def coordinate(self) -> Coordinate:
        return (self.x, self.y)


def _zero_ward_float_map() -> dict[int, float]:
    return {ward: 0.0 for ward in WARD_COORDINATE_RANGES}


def _zero_ward_int_map() -> dict[int, int]:
    return {ward: 0 for ward in WARD_COORDINATE_RANGES}


@dataclass(slots=True)
class WorldSummary:
    red_count: int = 0
    blue_count: int = 0
    green_count: int = 0
    red_density: float = 0.0
    blue_density: float = 0.0
    green_density: float = 0.0
    slum_density: float = 0.0
    central_slum_density: float = 0.0
    periphery_slum_density: float = 0.0
    avg_density: float = 0.0
    red_average_rent: float = 0.0
    green_average_rent: float = 0.0
    blue_average_rent: float = 0.0
    highest_rent: float = 0.0
    lowest_rent: float = 0.0
    num_searching: int = 0
    population: int = 0
    avg_income: float = 0.0
    avg_income_red: float = 0.0
    avg_income_blue: float = 0.0
    avg_income_green: float = 0.0
    slum_pop: int = 0
    central_slum_pop: int = 0
    peripheral_slum_pop: int = 0
    slum_pop_percent: float = 0.0
    num_slums: int = 0
    central_num_slums: int = 0
    peripheral_num_slums: int = 0
    slum_area_percent: float = 0.0
    central_slum_area_percent: float = 0.0
    periphery_slum_area_percent: float = 0.0
    smallest_slum: int = 0
    largest_slum: int = 0
    num_developers: int = 0
    ward_population: dict[int, int] = field(default_factory=_zero_ward_int_map)
    ward_slum_population: dict[int, int] = field(default_factory=_zero_ward_int_map)
    ward_slum_pop_percent: dict[int, float] = field(
        default_factory=_zero_ward_float_map
    )
    central_slum_pop_percent: float = 0.0
    periphery_slum_pop_percent: float = 0.0

    @property
    def slumpop(self) -> int:
        return self.slum_pop

    @property
    def central_slumpop(self) -> int:
        return self.central_slum_pop

    @property
    def peripheral_slumpop(self) -> int:
        return self.peripheral_slum_pop


@dataclass(slots=True)
class WorldState(Mapping[Coordinate, PatchState]):
    patches: dict[Coordinate, PatchState] = field(default_factory=dict)
    households: list[HouseholdState] = field(default_factory=list)
    developers: list[DeveloperState] = field(default_factory=list)
    time: int = 0
    city_income: float = 0.0
    summary: WorldSummary = field(default_factory=WorldSummary)

    def __getitem__(self, coordinate: Coordinate) -> PatchState:
        return self.patches[coordinate]

    def __iter__(self) -> Iterator[Coordinate]:
        return iter(self.patches)

    def __len__(self) -> int:
        return len(self.patches)

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        return WORLD_BOUNDS

    @property
    def width(self) -> int:
        return WORLD_WIDTH

    @property
    def height(self) -> int:
        return WORLD_HEIGHT

    @property
    def patch_count(self) -> int:
        return len(self.patches)

    def patch_at(self, x: int, y: int) -> PatchState:
        return self.patches[(x, y)]


def ward_for_coordinate(x: int, y: int) -> int:
    for ward, coordinate_range in WARD_COORDINATE_RANGES.items():
        if (
            coordinate_range.x_min <= x <= coordinate_range.x_max
            and coordinate_range.y_min <= y <= coordinate_range.y_max
        ):
            return ward

    raise ValueError(
        f"Coordinate ({x}, {y}) is outside Slumulation world bounds {WORLD_BOUNDS}."
    )


def is_central_ward(ward: int) -> bool:
    _validate_ward(ward)
    return ward == CENTRAL_WARD


def is_peripheral_ward(ward: int) -> bool:
    _validate_ward(ward)
    return ward in PERIPHERAL_WARDS


def build_empty_world() -> WorldState:
    patches: dict[Coordinate, PatchState] = {}

    for y in range(WORLD_Y_MIN, WORLD_Y_MAX + 1):
        for x in range(WORLD_X_MIN, WORLD_X_MAX + 1):
            ward = ward_for_coordinate(x, y)
            patches[(x, y)] = PatchState(x=x, y=y, ward=ward)

    if len(patches) != WORLD_PATCH_COUNT:
        raise RuntimeError(
            f"Expected {WORLD_PATCH_COUNT} patches, created {len(patches)}."
        )

    return WorldState(patches=patches)


def _validate_ward(ward: int) -> None:
    if ward not in WARD_COORDINATE_RANGES:
        raise ValueError(f"Unknown Slumulation ward: {ward}.")


__all__ = [
    "Coordinate",
    "DeveloperState",
    "HouseholdState",
    "LandState",
    "PatchState",
    "WorldSummary",
    "WorldState",
    "build_empty_world",
    "is_central_ward",
    "is_peripheral_ward",
    "ward_for_coordinate",
]
