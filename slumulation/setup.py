from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from fractions import Fraction
from random import Random
from statistics import fmean, stdev
from typing import Any

from .constants import (
    BASELINE_PARAMETER_VALUES,
    CENTRAL_WARD,
    NetLogoValue,
    PARAMETER_CROSSWALK_BY_MESA_ALIAS,
    PARAMETER_CROSSWALK_BY_NETLOGO_NAME,
    PARAMETER_FIELD_ORDER,
    WARD_COORDINATE_RANGES,
)
from .state import (
    Coordinate,
    DeveloperState,
    HouseholdState,
    PatchState,
    WorldState,
    WorldSummary,
    build_empty_world,
)

SETUP_MAX_RENT = 1000
_UNSET = object()


@dataclass(frozen=True, slots=True)
class SetupParameters:
    staying_power: float
    percent_inappropriate_land: float
    informality_index: float
    percent_prime_land: float
    initial_city_limit: int
    population_growth_rate: float
    simulation_runtime: int
    politics: bool
    develop: bool
    price_sensitivity: float
    diffusion_rate: float
    economic_growth_rate: float
    initial_inequality: float
    netlogo_values: tuple[tuple[str, NetLogoValue], ...]

    @property
    def values(self) -> tuple[tuple[str, NetLogoValue], ...]:
        return self.netlogo_values

    @property
    def parameters(self) -> dict[str, NetLogoValue]:
        return dict(self.netlogo_values)

    @property
    def parameter_values(self) -> dict[str, NetLogoValue]:
        return self.parameters


@dataclass(frozen=True, slots=True)
class SetupInitialization:
    world: WorldState
    parameters: SetupParameters
    seed: Any
    max_rent: float
    min_rent: float
    strict_core_coordinates: tuple[Coordinate, ...]
    inclusive_core_coordinates: tuple[Coordinate, ...]
    selected_coordinates: tuple[Coordinate, ...]
    prime_coordinates: tuple[Coordinate, ...]
    inappropriate_coordinates: tuple[Coordinate, ...]
    remaining_coordinates: tuple[Coordinate, ...]

    def __getitem__(self, coordinate: Coordinate) -> PatchState:
        return self.world[coordinate]

    def __iter__(self) -> Iterator[Coordinate]:
        return iter(self.world)

    def __len__(self) -> int:
        return len(self.world)

    @property
    def patches(self) -> dict[Coordinate, PatchState]:
        return self.world.patches

    @property
    def households(self) -> list[HouseholdState]:
        return self.world.households

    @property
    def developers(self) -> list[DeveloperState]:
        return self.world.developers

    @property
    def time(self) -> int:
        return self.world.time

    @property
    def city_income(self) -> float:
        return self.world.city_income

    @property
    def summary(self) -> WorldSummary:
        return self.world.summary

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        return self.world.bounds

    @property
    def width(self) -> int:
        return self.world.width

    @property
    def height(self) -> int:
        return self.world.height

    @property
    def patch_count(self) -> int:
        return self.world.patch_count

    def patch_at(self, x: int, y: int) -> PatchState:
        return self.world.patch_at(x, y)


def load_setup_parameters(parameter_values: object | None = None) -> SetupParameters:
    raw_values: dict[str, object] = dict(BASELINE_PARAMETER_VALUES)

    if isinstance(parameter_values, SetupParameters):
        return parameter_values

    if parameter_values is not None:
        for key, value in _coerce_parameter_mapping(parameter_values).items():
            raw_values[_canonical_parameter_name(key)] = value

    staying_power = _as_float(raw_values["staying-power"], "staying-power")
    percent_inappropriate_land = _as_float(
        raw_values["percent-inappropriate-land"],
        "percent-inappropriate-land",
    )
    informality_index = _as_float(raw_values["informalityindex"], "informalityindex")
    percent_prime_land = _as_float(
        raw_values["percent-prime-land"],
        "percent-prime-land",
    )
    initial_city_limit = _as_int(raw_values["initialcitylimit"], "initialcitylimit")
    population_growth_rate = _as_float(raw_values["popgrowthrate"], "popgrowthrate")
    simulation_runtime = _as_int(raw_values["SimulationRuntime"], "SimulationRuntime")
    politics = _as_bool(raw_values["Politics"], "Politics")
    develop = _as_bool(raw_values["Develop"], "Develop")
    price_sensitivity = _as_float(raw_values["price-sensitivity"], "price-sensitivity")
    diffusion_rate = _as_float(raw_values["diffusion-rate"], "diffusion-rate")
    economic_growth_rate = _as_float(
        raw_values["economicgrowthrate"],
        "economicgrowthrate",
    )
    initial_inequality = _as_float(
        raw_values["initialinequality"],
        "initialinequality",
    )

    if initial_city_limit < 0:
        raise ValueError("initialcitylimit must be non-negative for setup.")
    if initial_inequality <= 0:
        raise ValueError("initialinequality must be greater than zero for setup.")
    if percent_inappropriate_land < 0 or percent_prime_land < 0:
        raise ValueError(
            "percent-prime-land and percent-inappropriate-land must be non-negative."
        )
    if not 0 <= informality_index <= 1:
        raise ValueError("informalityindex must be between 0 and 1 for setup.")

    normalized_values: dict[str, NetLogoValue] = {
        "staying-power": staying_power,
        "percent-inappropriate-land": percent_inappropriate_land,
        "informalityindex": informality_index,
        "percent-prime-land": percent_prime_land,
        "initialcitylimit": initial_city_limit,
        "popgrowthrate": population_growth_rate,
        "SimulationRuntime": simulation_runtime,
        "Politics": politics,
        "Develop": develop,
        "price-sensitivity": price_sensitivity,
        "diffusion-rate": diffusion_rate,
        "economicgrowthrate": economic_growth_rate,
        "initialinequality": initial_inequality,
    }

    return SetupParameters(
        staying_power=staying_power,
        percent_inappropriate_land=percent_inappropriate_land,
        informality_index=informality_index,
        percent_prime_land=percent_prime_land,
        initial_city_limit=initial_city_limit,
        population_growth_rate=population_growth_rate,
        simulation_runtime=simulation_runtime,
        politics=politics,
        develop=develop,
        price_sensitivity=price_sensitivity,
        diffusion_rate=diffusion_rate,
        economic_growth_rate=economic_growth_rate,
        initial_inequality=initial_inequality,
        netlogo_values=tuple(
            (name, normalized_values[name]) for name in PARAMETER_FIELD_ORDER
        ),
    )


def setup_initial_world(
    parameter_values: object | None = None,
    seed: Any = _UNSET,
    *,
    parameters: object | None = None,
) -> SetupInitialization:
    if seed is _UNSET:
        raise TypeError("setup_initial_world requires an explicit seed.")
    if seed is None:
        raise ValueError("setup_initial_world requires a non-None seed.")
    if parameter_values is not None and parameters is not None:
        raise TypeError("Pass either parameter_values or parameters, not both.")

    setup_parameters = load_setup_parameters(
        parameter_values if parameters is None else parameters
    )
    rng = Random(seed)
    world = build_empty_world()

    max_rent = SETUP_MAX_RENT
    min_rent = max_rent / setup_parameters.initial_inequality
    strict_core_coordinates = _core_coordinates(
        world,
        setup_parameters.initial_city_limit,
        inclusive=False,
    )
    inclusive_core_coordinates = _core_coordinates(
        world,
        setup_parameters.initial_city_limit,
        inclusive=True,
    )

    selected_count = _selected_land_count(
        parameters=setup_parameters,
        strict_core_count=len(strict_core_coordinates),
        inclusive_core_count=len(inclusive_core_coordinates),
    )
    selected_coordinates = tuple(rng.sample(strict_core_coordinates, selected_count))
    selected_coordinate_set = set(selected_coordinates)

    total_selected_land_percent = (
        setup_parameters.percent_prime_land
        + setup_parameters.percent_inappropriate_land
    )
    if selected_count > 0 and total_selected_land_percent == 0:
        raise ValueError(
            "Cannot assign selected land type when prime and inappropriate "
            "percentages sum to zero."
        )
    prime_probability = (
        setup_parameters.percent_prime_land / total_selected_land_percent
        if total_selected_land_percent
        else 0.0
    )

    prime_coordinates: list[Coordinate] = []
    inappropriate_coordinates: list[Coordinate] = []
    for coordinate in selected_coordinates:
        patch = world[coordinate]
        if rng.random() < prime_probability:
            patch.rent = max_rent
            prime_coordinates.append(coordinate)
        else:
            patch.rent = min_rent
            inappropriate_coordinates.append(coordinate)
        _sprout_initial_household(world, coordinate)

    remaining_coordinates: list[Coordinate] = []
    for coordinate in inclusive_core_coordinates:
        if coordinate in selected_coordinate_set:
            continue

        patch = world[coordinate]
        if patch.rent == 0:
            patch.rent = rng.random() * (max_rent - min_rent)
            _sprout_initial_household(world, coordinate)
            remaining_coordinates.append(coordinate)

    for patch in world.patches.values():
        patch.rent_payable = patch.rent

    for household in world.households:
        patch = world[household.coordinate]
        household.income = 3.3 * patch.rent
        household.informal = rng.random() < setup_parameters.informality_index

    _post_process_initial_setup(world, setup_parameters)
    _finalize_initial_globals(world)

    return SetupInitialization(
        world=world,
        parameters=setup_parameters,
        seed=seed,
        max_rent=max_rent,
        min_rent=min_rent,
        strict_core_coordinates=strict_core_coordinates,
        inclusive_core_coordinates=inclusive_core_coordinates,
        selected_coordinates=selected_coordinates,
        prime_coordinates=tuple(prime_coordinates),
        inappropriate_coordinates=tuple(inappropriate_coordinates),
        remaining_coordinates=tuple(remaining_coordinates),
    )


def _coerce_parameter_mapping(parameter_values: object) -> Mapping[object, object]:
    if isinstance(parameter_values, Mapping):
        for wrapper_key in ("parameter_values", "parameters", "netlogo_parameters"):
            if wrapper_key in parameter_values:
                return _coerce_parameter_mapping(parameter_values[wrapper_key])
        return parameter_values

    for attribute_name in (
        "parameter_values",
        "parameters",
        "netlogo_parameters",
        "values",
    ):
        if hasattr(parameter_values, attribute_name):
            attribute_value = getattr(parameter_values, attribute_name)
            if callable(attribute_value):
                attribute_value = attribute_value()
            try:
                return _coerce_parameter_mapping(attribute_value)
            except TypeError:
                pass

    pairs = _dict_from_pairs(parameter_values)
    if pairs is not None:
        return pairs

    raise TypeError(
        "setup parameters must be a mapping, a ParameterCombination-like object, "
        "or an iterable of parameter pairs."
    )


def _dict_from_pairs(value: object) -> dict[object, object] | None:
    if isinstance(value, (str, bytes, bytearray, Mapping)):
        return None

    try:
        return dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _canonical_parameter_name(key: object) -> str:
    if not isinstance(key, str):
        raise TypeError(f"Slumulation parameter names must be strings, got {key!r}.")

    if key in PARAMETER_CROSSWALK_BY_NETLOGO_NAME:
        return key

    alias_entry = PARAMETER_CROSSWALK_BY_MESA_ALIAS.get(key)
    if alias_entry is not None:
        return alias_entry.netlogo_name

    raise ValueError(f"Unknown Slumulation parameter: {key!r}.")


def _as_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be numeric, got {value!r}.")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be numeric, got {value!r}.") from exc

    raise TypeError(f"{name} must be numeric, got {value!r}.")


def _as_int(value: object, name: str) -> int:
    number = _as_float(value, name)
    if not number.is_integer():
        raise ValueError(f"{name} must be an integer value, got {value!r}.")
    return int(number)


def _as_bool(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False

    raise TypeError(f"{name} must be a boolean value, got {value!r}.")


def _core_coordinates(
    world: WorldState,
    initial_city_limit: int,
    *,
    inclusive: bool,
) -> tuple[Coordinate, ...]:
    if inclusive:
        return tuple(
            coordinate
            for coordinate in sorted(world.patches)
            if abs(coordinate[0]) <= initial_city_limit
            and abs(coordinate[1]) <= initial_city_limit
        )

    return tuple(
        coordinate
        for coordinate in sorted(world.patches)
        if abs(coordinate[0]) < initial_city_limit
        and abs(coordinate[1]) < initial_city_limit
    )


def _selected_land_count(
    *,
    parameters: SetupParameters,
    strict_core_count: int,
    inclusive_core_count: int,
) -> int:
    selected_count = (
        _fraction(parameters.percent_prime_land) * inclusive_core_count / 100
        + _fraction(parameters.percent_inappropriate_land) * strict_core_count / 100
    )

    if selected_count.denominator != 1:
        raise ValueError(
            "Initial selected land count is non-integral for the provided setup "
            f"parameters: {selected_count}."
        )

    selected_count_int = int(selected_count)
    if selected_count_int < 0:
        raise ValueError(
            f"Initial selected land count cannot be negative: {selected_count_int}."
        )
    if selected_count_int > strict_core_count:
        raise ValueError(
            "Initial selected land count cannot exceed the strict initial city core: "
            f"{selected_count_int} > {strict_core_count}."
        )
    return selected_count_int


def _fraction(value: float) -> Fraction:
    return Fraction(str(value))


def _sprout_initial_household(world: WorldState, coordinate: Coordinate) -> None:
    patch = world[coordinate]
    world.households.append(
        HouseholdState(
            x=patch.x,
            y=patch.y,
            old=0,
            stay=0,
            num_houses=1,
        )
    )
    patch.num_occupants += 1
    patch.occupied = patch.num_occupants > 0


def _post_process_initial_setup(
    world: WorldState,
    parameters: SetupParameters,
) -> None:
    households_by_coordinate = _households_by_coordinate(world)

    _update_initial_household_classes(world.households)
    _update_initial_household_searching(
        world,
        parameters,
        households_by_coordinate,
    )
    _update_initial_household_willingness(world, parameters)
    _update_initial_patch_occupancy(world, households_by_coordinate)
    _update_initial_patch_availability(world, households_by_coordinate)
    _update_initial_patch_residential_categories(world, households_by_coordinate)
    _update_initial_patch_slum_status(world)


def _finalize_initial_globals(world: WorldState) -> None:
    world.time = 0
    world.city_income = sum(household.income for household in world.households)
    world.summary = _update_initial_variables(world)


def _update_initial_variables(world: WorldState) -> WorldSummary:
    patches = tuple(world.patches.values())
    occupied_patches = tuple(patch for patch in patches if patch.occupied)
    central_occupied_patches = tuple(
        patch for patch in occupied_patches if patch.ward == CENTRAL_WARD
    )
    peripheral_occupied_patches = tuple(
        patch for patch in occupied_patches if patch.ward != CENTRAL_WARD
    )
    slum_patches = tuple(patch for patch in patches if patch.slum)
    central_slum_patches = tuple(
        patch for patch in slum_patches if patch.ward == CENTRAL_WARD
    )
    peripheral_slum_patches = tuple(
        patch for patch in slum_patches if patch.ward != CENTRAL_WARD
    )

    red_households = _households_with_class(world, "red")
    blue_households = _households_with_class(world, "blue")
    green_households = _households_with_class(world, "green")
    population = len(world.households)
    slum_pop = sum(patch.slum_occupants for patch in patches)
    central_slum_pop = sum(patch.slum_occupants for patch in central_slum_patches)
    peripheral_slum_pop = sum(patch.slum_occupants for patch in peripheral_slum_patches)
    ward_population = {
        ward: sum(patch.num_occupants for patch in patches if patch.ward == ward)
        for ward in sorted(WARD_COORDINATE_RANGES)
    }
    ward_slum_population = {
        ward: sum(patch.slum_occupants for patch in patches if patch.ward == ward)
        for ward in sorted(WARD_COORDINATE_RANGES)
    }
    ward_slum_pop_percent = {
        ward: _safe_divide(ward_slum_population[ward], ward_population[ward])
        for ward in sorted(WARD_COORDINATE_RANGES)
    }
    peripheral_population = sum(
        patch.num_occupants for patch in patches if patch.ward != CENTRAL_WARD
    )

    num_slums = len(slum_patches)
    central_num_slums = len(central_slum_patches)
    peripheral_num_slums = len(peripheral_slum_patches)
    slum_sizes = [patch.slum_occupants for patch in slum_patches]

    return WorldSummary(
        red_count=len(red_households),
        blue_count=len(blue_households),
        green_count=len(green_households),
        red_density=_safe_divide(
            len(red_households),
            _patch_count_with_resicat(patches, 3),
        ),
        blue_density=_safe_divide(
            len(blue_households),
            _patch_count_with_resicat(patches, 2),
        ),
        green_density=_safe_divide(
            len(green_households),
            _patch_count_with_resicat(patches, 1),
        ),
        slum_density=_safe_divide(slum_pop, num_slums),
        central_slum_density=_safe_divide(central_slum_pop, central_num_slums),
        periphery_slum_density=_safe_divide(
            peripheral_slum_pop,
            peripheral_num_slums,
        ),
        avg_density=_safe_divide(population, len(occupied_patches)),
        red_average_rent=_average_rent_payable(world, red_households),
        green_average_rent=_average_rent_payable(world, green_households),
        blue_average_rent=_average_rent_payable(world, blue_households),
        highest_rent=max((patch.rent for patch in patches), default=0.0),
        lowest_rent=min((patch.rent for patch in patches), default=0.0),
        num_searching=sum(household.searching for household in world.households),
        population=population,
        avg_income=_safe_divide(world.city_income, population),
        avg_income_red=_average_income(red_households),
        avg_income_blue=_average_income(blue_households),
        avg_income_green=_average_income(green_households),
        slum_pop=slum_pop,
        central_slum_pop=central_slum_pop,
        peripheral_slum_pop=peripheral_slum_pop,
        slum_pop_percent=_safe_divide(slum_pop, population),
        num_slums=num_slums,
        central_num_slums=central_num_slums,
        peripheral_num_slums=peripheral_num_slums,
        slum_area_percent=_safe_divide(num_slums, len(occupied_patches)) * 100,
        central_slum_area_percent=_safe_divide(
            central_num_slums,
            len(central_occupied_patches),
        )
        * 100,
        periphery_slum_area_percent=_safe_divide(
            peripheral_num_slums,
            len(peripheral_occupied_patches),
        )
        * 100,
        smallest_slum=min(slum_sizes, default=0),
        largest_slum=min(slum_sizes, default=0),
        num_developers=len(world.developers),
        ward_population=ward_population,
        ward_slum_population=ward_slum_population,
        ward_slum_pop_percent=ward_slum_pop_percent,
        central_slum_pop_percent=ward_slum_pop_percent[CENTRAL_WARD] * 100,
        periphery_slum_pop_percent=_safe_divide(
            peripheral_slum_pop,
            peripheral_population,
        )
        * 100,
    )


def _households_by_coordinate(
    world: WorldState,
) -> dict[Coordinate, list[HouseholdState]]:
    households_by_coordinate: dict[Coordinate, list[HouseholdState]] = {}

    for household in world.households:
        households_by_coordinate.setdefault(household.coordinate, []).append(household)

    return households_by_coordinate


def _households_with_class(
    world: WorldState,
    income_class: str,
) -> list[HouseholdState]:
    return [
        household
        for household in world.households
        if household.income_class == income_class
    ]


def _patch_count_with_resicat(
    patches: tuple[PatchState, ...],
    resicat: int,
) -> int:
    return sum(patch.resicat == resicat for patch in patches)


def _average_income(households: list[HouseholdState]) -> float:
    return fmean(household.income for household in households) if households else 0.0


def _average_rent_payable(
    world: WorldState,
    households: list[HouseholdState],
) -> float:
    if not households:
        return 0.0

    return fmean(world[household.coordinate].rent_payable for household in households)


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _update_initial_household_classes(households: list[HouseholdState]) -> None:
    if not households:
        return

    incomes = [household.income for household in households]
    mean_income = fmean(incomes)
    income_standard_deviation = (
        stdev(incomes, xbar=mean_income) if len(incomes) > 1 else 0.0
    )
    upper_income_threshold = mean_income + 1.1 * income_standard_deviation
    lower_income_threshold = mean_income - 0.1 * income_standard_deviation

    for household in households:
        if household.income > upper_income_threshold:
            household.income_class = "green"
            household.class_updated = True
        elif household.income < lower_income_threshold:
            household.income_class = "red"
            household.class_updated = True
        elif lower_income_threshold < household.income < upper_income_threshold:
            household.income_class = "blue"
            household.class_updated = True


def _update_initial_household_searching(
    world: WorldState,
    parameters: SetupParameters,
    households_by_coordinate: Mapping[Coordinate, list[HouseholdState]],
) -> None:
    for household in world.households:
        patch = world[household.coordinate]
        rent_too_high = (
            patch.rent_payable > (1 + parameters.staying_power) * 0.3 * household.income
        )
        mixed_income_class = any(
            other_household is not household
            and other_household.income_class != household.income_class
            for other_household in households_by_coordinate[household.coordinate]
        )
        household.searching = rent_too_high or mixed_income_class


def _update_initial_household_willingness(
    world: WorldState,
    parameters: SetupParameters,
) -> None:
    for household in world.households:
        patch = world[household.coordinate]
        household.willing = (
            patch.rent_payable
            > (1 - parameters.price_sensitivity) * 0.3 * household.income
        )
        if household.income_class in {"green", "blue"}:
            household.willing = False


def _update_initial_patch_occupancy(
    world: WorldState,
    households_by_coordinate: Mapping[Coordinate, list[HouseholdState]],
) -> None:
    for patch in world.patches.values():
        patch.num_occupants = len(households_by_coordinate.get(patch.coordinate, ()))
        patch.occupied = patch.num_occupants > 0


def _update_initial_patch_availability(
    world: WorldState,
    households_by_coordinate: Mapping[Coordinate, list[HouseholdState]],
) -> None:
    for patch in world.patches.values():
        households = households_by_coordinate.get(patch.coordinate, ())

        if patch.num_occupants == 0:
            patch.occupied = False
            patch.available = True
        elif any(not household.willing for household in households):
            patch.available = False


def _update_initial_patch_residential_categories(
    world: WorldState,
    households_by_coordinate: Mapping[Coordinate, list[HouseholdState]],
) -> None:
    for patch in world.patches.values():
        households = households_by_coordinate.get(patch.coordinate, ())

        if patch.num_occupants > patch.num_units:
            patch.resicat = 4
        if any(household.income_class == "red" for household in households) and (
            not patch.slum
        ):
            patch.resicat = 3
        if any(household.income_class == "blue" for household in households) and (
            not patch.slum
        ):
            patch.resicat = 2
        if any(household.income_class == "green" for household in households) and (
            not patch.slum
        ):
            patch.resicat = 1
        if patch.num_occupants == 0:
            patch.resicat = 0


def _update_initial_patch_slum_status(world: WorldState) -> None:
    for patch in world.patches.values():
        patch.slum = patch.num_occupants > patch.num_units
        patch.slum_occupants = patch.num_occupants if patch.slum else 0


__all__ = [
    "SETUP_MAX_RENT",
    "SetupInitialization",
    "SetupParameters",
    "load_setup_parameters",
    "setup_initial_world",
]
