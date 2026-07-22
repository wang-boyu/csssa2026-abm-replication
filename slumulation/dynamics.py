from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import cos, floor, log, radians, sin
from random import Random
from statistics import fmean, stdev

from .constants import (
    CENTRAL_WARD,
    DEFAULT_MAX_SEARCH_ATTEMPTS,
    WARD_COORDINATE_RANGES,
    WORLD_X_MAX,
    WORLD_X_MIN,
    WORLD_Y_MAX,
    WORLD_Y_MIN,
)
from .setup import SetupParameters
from .state import (
    Coordinate,
    DeveloperState,
    HouseholdState,
    PatchState,
    WorldState,
    WorldSummary,
)


class SearchExhaustedError(RuntimeError):
    """Raised when source-recursive household search exceeds the safety guard."""


_HouseholdCoordinateLookup = Mapping[Coordinate, tuple[HouseholdState, ...]]


@dataclass(frozen=True)
class SlumulateStepResult:
    """Result of one source-ordered ``Slumulate`` schedule invocation."""

    stopped: bool
    tick_advanced: bool


def create_new_households(
    world: WorldState,
    parameters: SetupParameters,
    rng: Random,
) -> tuple[HouseholdState, ...]:
    """Apply only the source create-new-households procedure."""

    new_household_count = floor(
        parameters.population_growth_rate * world.summary.population / 100
    )
    if new_household_count < 0:
        raise ValueError(
            "create-new-households cannot create a negative household count: "
            f"{new_household_count}."
        )

    created_households: list[HouseholdState] = []
    for _ in range(new_household_count):
        household = HouseholdState(x=0, y=0)
        world.households.append(household)

        household.income = _random_exponential(world.summary.avg_income, rng)
        household.informal = rng.random() < parameters.informality_index
        _update_household_class(household, world.households)
        _update_household_willingness(world, parameters, household)
        household.searching = True
        household.old = 0
        household.stay = 0
        household.num_houses = 0
        created_households.append(household)

    return tuple(created_households)


def settle_households(
    world: WorldState,
    parameters: SetupParameters,
    rng: Random,
    *,
    max_search_attempts: int = DEFAULT_MAX_SEARCH_ATTEMPTS,
) -> tuple[HouseholdState, ...]:
    """Apply the bounded source settle-households slice.

    NetLogo asks a snapshot of ``households with [searching?]`` in random order.
    Each household starts from patch (0, 0), keeping its current heading, then
    performs the source random walk in ``find-house``.
    """

    searching_households = [
        household for household in world.households if household.searching
    ]
    rng.shuffle(searching_households)

    center_patch = world.patch_at(0, 0)
    for household in searching_households:
        move_to_patch(household, center_patch)
        find_house(
            world,
            parameters,
            household,
            rng,
            max_search_attempts=max_search_attempts,
        )

    return tuple(searching_households)


def update_households(
    world: WorldState,
    parameters: SetupParameters,
    rng: Random,
) -> tuple[HouseholdState, ...]:
    """Apply only the source ``update-households`` procedure.

    NetLogo asks a snapshot of all households in random order, then runs the
    full source-ordered block for each household before advancing to the next.
    """

    households = list(world.households)
    rng.shuffle(households)

    for household in households:
        _update_household_income(household, parameters)
        _update_household_willingness(world, parameters, household)
        _update_household_searching(world, parameters, rng, household)
        _update_household_class(household, world.households)
        _update_household_old(household)
        _update_household_stay(household)

    return tuple(households)


def update_patches(
    world: WorldState,
    parameters: SetupParameters,
) -> tuple[PatchState, ...]:
    """Apply only the source ``update-patches`` numeric patch-state slice."""

    patches = tuple(world.patches.values())
    _diffuse_patch_rent(world, patches, parameters.diffusion_rate)
    households_by_coordinate = _households_by_coordinate(world)

    for patch in patches:
        _update_patch_rent(patch, parameters)
        update_occupancy(world, patch, households_by_coordinate)
        update_resicat(world, patch, households_by_coordinate)
        update_slum_status(patch)
        update_availability(world, patch, households_by_coordinate)
        update_rent_payable(world, parameters, patch)

    return patches


def update_developers(world: WorldState) -> tuple[DeveloperState, ...]:
    """Apply only the source ``update-developers`` developer lifecycle slice."""

    developers = tuple(world.developers)
    for developer in developers:
        if not _developer_is_live(world, developer):
            continue

        _check_developer_no_role(world)
        if developer.no_role and _developer_is_live(world, developer):
            _remove_developer(world, developer)

    return developers


def slumulate_step(
    world: WorldState,
    parameters: SetupParameters,
    rng: Random,
) -> SlumulateStepResult:
    """Apply one source-ordered NetLogo ``Slumulate`` invocation.

    This helper deliberately stops at the model schedule boundary. BehaviorSpace
    step accounting, output rows, plots, and validation remain runner concerns.
    """

    create_new_households(world, parameters, rng)
    settle_households(world, parameters, rng)
    update_households(world, parameters, rng)
    update_patches(world, parameters)
    update_developers(world)
    update_city_income(world, parameters)
    update_variables(world)
    update_time(world)

    if should_stop(world, parameters):
        return SlumulateStepResult(stopped=True, tick_advanced=False)
    return SlumulateStepResult(stopped=False, tick_advanced=True)


def update_city_income(world: WorldState, parameters: SetupParameters) -> None:
    """Apply only the source ``update-cityincome`` procedure."""

    world.city_income += (parameters.economic_growth_rate / 100) * world.city_income


def update_variables(world: WorldState) -> None:
    """Refresh annual source globals into ``world.summary``.

    NetLogo leaves guarded assignments stale when their guards are false. This
    helper builds a fresh summary from current annual state while carrying those
    guarded prior values forward from the previous summary.
    """

    previous = world.summary
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

    red_households = _households_with_income_class(world, "red")
    green_households = _households_with_income_class(world, "green")
    blue_households = _households_with_income_class(world, "blue")

    red_count = len(red_households)
    green_count = len(green_households)
    blue_count = len(blue_households)

    red_density = red_count / _patch_count_with_resicat(patches, 3)
    blue_density = blue_count / _patch_count_with_resicat(patches, 2)
    green_density = green_count / _patch_count_with_resicat(patches, 1)
    avg_density = len(world.households) / len(occupied_patches)

    red_average_rent = _average_current_patch_rent_payable(world, red_households)
    green_average_rent = _average_current_patch_rent_payable(world, green_households)
    blue_average_rent = _average_current_patch_rent_payable(world, blue_households)
    highest_rent = max(patch.rent for patch in patches)
    lowest_rent = min(patch.rent for patch in patches)

    num_searching = sum(1 for household in world.households if household.searching)
    population = len(world.households)

    avg_income_red = _average_income(red_households)
    avg_income_green = _average_income(green_households)
    avg_income_blue = _average_income(blue_households)
    avg_income = world.city_income / population

    slum_pop = sum(patch.slum_occupants for patch in patches)
    central_slum_pop = sum(
        patch.slum_occupants for patch in patches if patch.ward == CENTRAL_WARD
    )
    peripheral_slum_pop = sum(
        patch.slum_occupants for patch in patches if patch.ward != CENTRAL_WARD
    )
    slum_pop_percent = slum_pop / population
    num_slums = len(slum_patches)
    central_num_slums = len(central_slum_patches)
    peripheral_num_slums = len(peripheral_slum_patches)
    slum_area_percent = (num_slums / len(occupied_patches)) * 100
    central_slum_area_percent = (
        central_num_slums / len(central_occupied_patches)
    ) * 100
    periphery_slum_area_percent = previous.periphery_slum_area_percent
    if peripheral_occupied_patches:
        periphery_slum_area_percent = (
            peripheral_num_slums / len(peripheral_occupied_patches)
        ) * 100

    slum_density = previous.slum_density
    smallest_slum = previous.smallest_slum
    largest_slum = previous.largest_slum
    if num_slums > 0:
        slum_density = slum_pop / num_slums
        smallest_slum = min(patch.slum_occupants for patch in slum_patches)
        largest_slum = min(patch.slum_occupants for patch in slum_patches)

    central_slum_density = previous.central_slum_density
    if central_num_slums > 0:
        central_slum_density = central_slum_pop / central_num_slums

    periphery_slum_density = previous.periphery_slum_density
    if peripheral_num_slums > 0:
        periphery_slum_density = peripheral_slum_pop / peripheral_num_slums

    num_developers = len(world.developers)

    ward_population = {
        ward: sum(patch.num_occupants for patch in patches if patch.ward == ward)
        for ward in sorted(WARD_COORDINATE_RANGES)
    }
    ward_slum_population = {
        ward: sum(patch.slum_occupants for patch in patches if patch.ward == ward)
        for ward in sorted(WARD_COORDINATE_RANGES)
    }
    ward_slum_pop_percent = {
        ward: previous.ward_slum_pop_percent.get(ward, 0.0)
        for ward in sorted(WARD_COORDINATE_RANGES)
    }
    for ward, ward_pop in ward_population.items():
        if ward_pop > 0:
            ward_slum_pop_percent[ward] = ward_slum_population[ward] / ward_pop

    central_slum_pop_percent = ward_slum_pop_percent[CENTRAL_WARD] * 100
    peripheral_population = sum(
        patch.num_occupants for patch in patches if patch.ward != CENTRAL_WARD
    )
    periphery_slum_pop_percent = previous.periphery_slum_pop_percent
    if peripheral_population > 0:
        periphery_slum_pop_percent = (peripheral_slum_pop / peripheral_population) * 100

    world.summary = WorldSummary(
        red_count=red_count,
        blue_count=blue_count,
        green_count=green_count,
        red_density=red_density,
        blue_density=blue_density,
        green_density=green_density,
        slum_density=slum_density,
        central_slum_density=central_slum_density,
        periphery_slum_density=periphery_slum_density,
        avg_density=avg_density,
        red_average_rent=red_average_rent,
        green_average_rent=green_average_rent,
        blue_average_rent=blue_average_rent,
        highest_rent=highest_rent,
        lowest_rent=lowest_rent,
        num_searching=num_searching,
        population=population,
        avg_income=avg_income,
        avg_income_red=avg_income_red,
        avg_income_blue=avg_income_blue,
        avg_income_green=avg_income_green,
        slum_pop=slum_pop,
        central_slum_pop=central_slum_pop,
        peripheral_slum_pop=peripheral_slum_pop,
        slum_pop_percent=slum_pop_percent,
        num_slums=num_slums,
        central_num_slums=central_num_slums,
        peripheral_num_slums=peripheral_num_slums,
        slum_area_percent=slum_area_percent,
        central_slum_area_percent=central_slum_area_percent,
        periphery_slum_area_percent=periphery_slum_area_percent,
        smallest_slum=smallest_slum,
        largest_slum=largest_slum,
        num_developers=num_developers,
        ward_population=ward_population,
        ward_slum_population=ward_slum_population,
        ward_slum_pop_percent=ward_slum_pop_percent,
        central_slum_pop_percent=central_slum_pop_percent,
        periphery_slum_pop_percent=periphery_slum_pop_percent,
    )


def update_time(world: WorldState) -> None:
    """Apply only the source ``update-time`` procedure."""

    world.time += 1


def should_stop(world: WorldState, parameters: SetupParameters) -> bool:
    return world.time > parameters.simulation_runtime


def find_house(
    world: WorldState,
    parameters: SetupParameters,
    household: HouseholdState,
    rng: Random,
    *,
    max_search_attempts: int = DEFAULT_MAX_SEARCH_ATTEMPTS,
) -> PatchState:
    """Run guarded NetLogo-style ``find-house`` for one household.

    The source procedure is recursive and does not ``stop`` after the recursive
    call, so successful settlement side effects run once per active recursive
    frame. This iterative implementation preserves that unwind behavior by
    applying the post-success block once for every search attempt.
    """

    if max_search_attempts < 1:
        raise ValueError(
            f"find_house requires max_search_attempts >= 1, got {max_search_attempts}."
        )

    other_households_by_coordinate = _households_by_coordinate(
        world,
        excluded_household=household,
    )
    last_rejection_context: dict[str, object] | None = None
    attempts = 0
    while attempts < max_search_attempts:
        attempts += 1
        right_turn(household, rng.random() * 360)
        forward(household, rng.random())

        candidate_patch = patch_here(world, household)
        rejection_context = _rejection_context(
            world,
            household,
            candidate_patch,
            other_households_by_coordinate,
        )
        if not rejection_context["rejected"]:
            settled_patch = candidate_patch
            households_by_coordinate = _households_by_coordinate(world)
            for _ in range(attempts):
                settled_patch = _apply_find_house_success(
                    world,
                    parameters,
                    household,
                    households_by_coordinate,
                )
            return settled_patch

        last_rejection_context = rejection_context

    raise SearchExhaustedError(
        "find_house exhausted max_search_attempts="
        f"{max_search_attempts} after {attempts} attempts for "
        f"{_household_context(household)} at current_patch="
        f"{_patch_context(patch_here(world, household))}; "
        f"last_rejection_context={last_rejection_context!r}."
    )


def move_to_patch(household: HouseholdState, patch: PatchState) -> None:
    """Move a household to a patch center without changing its heading."""

    household.xcor = float(patch.x)
    household.ycor = float(patch.y)
    household.x = patch.x
    household.y = patch.y


def right_turn(household: HouseholdState, degrees: float) -> None:
    household.heading = (household.heading + degrees) % 360.0


def forward(household: HouseholdState, distance: float) -> None:
    heading_radians = radians(household.heading)
    xcor, ycor = _continuous_position(household)

    household.xcor = wrap_continuous_coordinate(
        xcor + distance * sin(heading_radians),
        WORLD_X_MIN,
        WORLD_X_MAX,
    )
    household.ycor = wrap_continuous_coordinate(
        ycor + distance * cos(heading_radians),
        WORLD_Y_MIN,
        WORLD_Y_MAX,
    )
    household.x, household.y = patch_here_coordinate(household)


def wrap_continuous_coordinate(
    value: float,
    minimum_patch_coordinate: int,
    maximum_patch_coordinate: int,
) -> float:
    width = maximum_patch_coordinate - minimum_patch_coordinate + 1
    lower_edge = minimum_patch_coordinate - 0.5
    return ((value - lower_edge) % width) + lower_edge


def patch_here_coordinate(household: HouseholdState) -> Coordinate:
    xcor, ycor = _continuous_position(household)
    return (
        _continuous_to_patch_coordinate(xcor, WORLD_X_MIN, WORLD_X_MAX),
        _continuous_to_patch_coordinate(ycor, WORLD_Y_MIN, WORLD_Y_MAX),
    )


def patch_here(world: WorldState, household: HouseholdState) -> PatchState:
    return world.patch_at(*patch_here_coordinate(household))


def update_occupancy(
    world: WorldState,
    patch: PatchState,
    households_by_coordinate: _HouseholdCoordinateLookup | None = None,
) -> None:
    patch.num_occupants = len(_households_here(world, patch, households_by_coordinate))
    patch.occupied = patch.num_occupants > 0


def update_availability(
    world: WorldState,
    patch: PatchState,
    households_by_coordinate: _HouseholdCoordinateLookup | None = None,
) -> None:
    has_developer = _developers_here(world, patch)
    households = _households_here(world, patch, households_by_coordinate)

    if has_developer:
        if patch.num_occupants < patch.num_units:
            patch.available = True
        if patch.num_occupants == patch.num_units:
            patch.available = False

    if not has_developer:
        if patch.num_occupants > 0:
            if any(not household.willing for household in households):
                patch.available = False
        else:
            patch.occupied = False
            patch.available = True


def update_slum_status(patch: PatchState) -> None:
    if patch.num_occupants > patch.num_units:
        patch.slum = True
        patch.slum_occupants = patch.num_occupants
    if patch.num_occupants < patch.num_units:
        patch.slum = False
        patch.slum_occupants = 0
    if patch.num_occupants == patch.num_units:
        patch.slum = False
        patch.slum_occupants = 0


def update_resicat(
    world: WorldState,
    patch: PatchState,
    households_by_coordinate: _HouseholdCoordinateLookup | None = None,
) -> None:
    households = _households_here(world, patch, households_by_coordinate)

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


def update_rent_payable(
    world: WorldState,
    parameters: SetupParameters,
    patch: PatchState,
) -> None:
    has_developer = _developers_here(world, patch)

    if has_developer:
        patch.rent_payable = patch.rent / patch.num_units

    if not has_developer:
        if not patch.slum:
            patch.rent_payable = patch.rent / patch.num_units
        if patch.slum:
            patch.rent_payable = patch.rent / patch.num_occupants
            if parameters.politics:
                ward_slum_share = world.summary.ward_slum_pop_percent.get(
                    patch.ward,
                    0.0,
                )
                patch.rent_payable = (1 - ward_slum_share) * patch.rent_payable


def _diffuse_patch_rent(
    world: WorldState,
    patches: Sequence[PatchState],
    diffusion_rate: float,
) -> None:
    old_rents = {patch.coordinate: patch.rent for patch in patches}
    diffused_rents: dict[Coordinate, float] = {}
    neighbor_share = diffusion_rate / 8

    for patch in patches:
        neighbor_rent = sum(
            old_rents[neighbor.coordinate]
            for neighbor in _wrapped_patch_neighbors(world, patch)
        )
        diffused_rents[patch.coordinate] = (1 - diffusion_rate) * old_rents[
            patch.coordinate
        ] + neighbor_share * neighbor_rent

    for patch in patches:
        patch.rent = diffused_rents[patch.coordinate]


def _wrapped_patch_neighbors(
    world: WorldState,
    patch: PatchState,
) -> tuple[PatchState, ...]:
    neighbors: list[PatchState] = []
    for y_offset in (-1, 0, 1):
        for x_offset in (-1, 0, 1):
            if x_offset == 0 and y_offset == 0:
                continue
            neighbors.append(
                world.patch_at(
                    _wrap_patch_axis(patch.x + x_offset, WORLD_X_MIN, WORLD_X_MAX),
                    _wrap_patch_axis(patch.y + y_offset, WORLD_Y_MIN, WORLD_Y_MAX),
                )
            )
    return tuple(neighbors)


def _wrap_patch_axis(
    value: int,
    minimum_patch_coordinate: int,
    maximum_patch_coordinate: int,
) -> int:
    width = maximum_patch_coordinate - minimum_patch_coordinate + 1
    return ((value - minimum_patch_coordinate) % width) + minimum_patch_coordinate


def _update_patch_rent(
    patch: PatchState,
    parameters: SetupParameters,
) -> None:
    patch.rent += ((0.5 * parameters.economic_growth_rate) / 100) * patch.rent


def _random_exponential(mean: float, rng: Random) -> float:
    if mean < 0:
        raise ValueError(f"random-exponential mean cannot be negative: {mean}.")
    if mean == 0:
        return 0.0

    draw = rng.random()
    while draw <= 0:
        draw = rng.random()
    return -mean * log(draw)


def _households_with_income_class(
    world: WorldState,
    income_class: str,
) -> tuple[HouseholdState, ...]:
    return tuple(
        household
        for household in world.households
        if household.income_class == income_class
    )


def _patch_count_with_resicat(
    patches: Sequence[PatchState],
    resicat: int,
) -> int:
    return sum(patch.resicat == resicat for patch in patches)


def _average_current_patch_rent_payable(
    world: WorldState,
    households: Sequence[HouseholdState],
) -> float:
    return fmean(world[household.coordinate].rent_payable for household in households)


def _average_income(households: Sequence[HouseholdState]) -> float:
    return fmean(household.income for household in households)


def _update_household_class(
    household: HouseholdState,
    households: Sequence[HouseholdState],
) -> None:
    if not households:
        return

    incomes = [other_household.income for other_household in households]
    mean_income = fmean(incomes)
    income_standard_deviation = (
        stdev(incomes, xbar=mean_income) if len(incomes) > 1 else 0.0
    )
    upper_income_threshold = mean_income + 1.1 * income_standard_deviation
    lower_income_threshold = mean_income - 0.1 * income_standard_deviation

    if household.income > upper_income_threshold:
        household.income_class = "green"
        household.class_updated = True
    if household.income < lower_income_threshold:
        household.income_class = "red"
        household.class_updated = True
    if (
        household.income < upper_income_threshold
        and household.income > lower_income_threshold
    ):
        household.income_class = "blue"
        household.class_updated = True


def _update_household_willingness(
    world: WorldState,
    parameters: SetupParameters,
    household: HouseholdState,
) -> None:
    patch = world[household.coordinate]
    household.willing = (
        patch.rent_payable > (1 - parameters.price_sensitivity) * 0.3 * household.income
    )
    if household.income_class in {"green", "blue"}:
        household.willing = False


def _update_household_income(
    household: HouseholdState,
    parameters: SetupParameters,
) -> None:
    growth_rate = parameters.economic_growth_rate / 100

    if household.informal and household.income_class == "red":
        household.income += growth_rate * 0.1 * household.income
    if (not household.informal) and household.income_class == "red":
        household.income += growth_rate * household.income
    if household.income_class in {"green", "blue"}:
        household.income += growth_rate * household.income


def _update_household_searching(
    world: WorldState,
    parameters: SetupParameters,
    rng: Random,
    household: HouseholdState,
) -> None:
    patch = world[household.coordinate]
    rent_pressure = (
        patch.rent_payable > (1 + parameters.staying_power) * 0.3 * household.income
    )

    if rent_pressure:
        household.searching = True
        _create_developer(world, parameters, rng, household)
    else:
        household.searching = False

    if any(
        other_household is not household
        and other_household.income_class != household.income_class
        for other_household in _households_here(world, patch)
    ):
        household.searching = True


def _update_household_old(household: HouseholdState) -> None:
    household.old += 1


def _update_household_stay(household: HouseholdState) -> None:
    household.stay += 1


def _create_developer(
    world: WorldState,
    parameters: SetupParameters,
    rng: Random,
    household: HouseholdState,
) -> DeveloperState | None:
    patch = world[household.coordinate]
    other_households_here = tuple(
        other_household
        for other_household in _households_here(world, patch)
        if other_household is not household
    )
    if (
        _developers_here(world, patch)
        or other_households_here
        or not parameters.develop
    ):
        return None

    developer = DeveloperState(x=patch.x, y=patch.y, no_role=False)
    world.developers.append(developer)
    patch.num_units += int(rng.random() * 3)
    patch.available = True
    patch.resicat = 0
    return developer


def _apply_find_house_success(
    world: WorldState,
    parameters: SetupParameters,
    household: HouseholdState,
    households_by_coordinate: _HouseholdCoordinateLookup | None = None,
) -> PatchState:
    current_patch = patch_here(world, household)
    move_to_patch(household, current_patch)
    household.searching = False
    household.stay = 0
    household.num_houses += 1
    update_occupancy(world, current_patch, households_by_coordinate)
    update_availability(world, current_patch, households_by_coordinate)
    update_slum_status(current_patch)
    update_resicat(world, current_patch, households_by_coordinate)
    update_rent_payable(world, parameters, current_patch)
    return current_patch


def _rejection_context(
    world: WorldState,
    household: HouseholdState,
    patch: PatchState,
    other_households_by_coordinate: _HouseholdCoordinateLookup | None = None,
) -> dict[str, object]:
    mixed_class_households = [
        other_household
        for other_household in _households_here(
            world,
            patch,
            other_households_by_coordinate,
        )
        if other_household.income_class != household.income_class
    ]
    rent_too_high = patch.rent_payable > 0.3 * household.income
    unavailable = not patch.available
    reasons = {
        "mixed_income_class": bool(mixed_class_households),
        "rent_too_high": rent_too_high,
        "unavailable": unavailable,
    }
    return {
        "rejected": any(reasons.values()),
        "reasons": reasons,
        "patch": _patch_context(patch),
        "mixed_household_classes": [
            other_household.income_class for other_household in mixed_class_households
        ],
        "rent_threshold": 0.3 * household.income,
    }


def _household_context(household: HouseholdState) -> dict[str, object]:
    xcor, ycor = _continuous_position(household)
    return {
        "coordinate": household.coordinate,
        "xcor": xcor,
        "ycor": ycor,
        "heading": household.heading,
        "income_class": household.income_class,
        "income": household.income,
        "searching": household.searching,
        "willing": household.willing,
        "num_houses": household.num_houses,
    }


def _patch_context(patch: PatchState) -> dict[str, object]:
    return {
        "coordinate": patch.coordinate,
        "rent_payable": patch.rent_payable,
        "available": patch.available,
        "occupied": patch.occupied,
        "num_occupants": patch.num_occupants,
        "num_units": patch.num_units,
        "slum": patch.slum,
        "slum_occupants": patch.slum_occupants,
        "resicat": patch.resicat,
        "ward": patch.ward,
    }


def _households_here(
    world: WorldState,
    patch: PatchState,
    households_by_coordinate: _HouseholdCoordinateLookup | None = None,
) -> tuple[HouseholdState, ...]:
    if households_by_coordinate is not None:
        return households_by_coordinate.get(patch.coordinate, ())

    return tuple(
        household
        for household in world.households
        if household.coordinate == patch.coordinate
    )


def _households_by_coordinate(
    world: WorldState,
    excluded_household: HouseholdState | None = None,
) -> _HouseholdCoordinateLookup:
    households_by_coordinate: dict[Coordinate, list[HouseholdState]] = {}
    for household in world.households:
        if household is excluded_household:
            continue
        households_by_coordinate.setdefault(household.coordinate, []).append(household)

    return {
        coordinate: tuple(households)
        for coordinate, households in households_by_coordinate.items()
    }


def _developers_here(world: WorldState, patch: PatchState) -> bool:
    return any(
        developer.coordinate == patch.coordinate for developer in world.developers
    )


def _check_developer_no_role(world: WorldState) -> None:
    for developer in _current_developers(world):
        patch = world[developer.coordinate]
        if patch.num_units == patch.num_occupants:
            developer.no_role = True

    for developer in _current_developers(world):
        patch = world[developer.coordinate]
        if patch.num_units < patch.num_occupants:
            developer.no_role = True


def _current_developers(world: WorldState) -> tuple[DeveloperState, ...]:
    return tuple(world.developers)


def _developer_is_live(world: WorldState, developer: DeveloperState) -> bool:
    return any(current_developer is developer for current_developer in world.developers)


def _remove_developer(world: WorldState, developer: DeveloperState) -> None:
    for index, current_developer in enumerate(world.developers):
        if current_developer is developer:
            del world.developers[index]
            return


def _continuous_position(household: HouseholdState) -> tuple[float, float]:
    if household.xcor is None:
        household.xcor = float(household.x)
    if household.ycor is None:
        household.ycor = float(household.y)
    return household.xcor, household.ycor


def _continuous_to_patch_coordinate(
    value: float,
    minimum_patch_coordinate: int,
    maximum_patch_coordinate: int,
) -> int:
    wrapped = wrap_continuous_coordinate(
        value,
        minimum_patch_coordinate,
        maximum_patch_coordinate,
    )
    patch_coordinate = floor(wrapped + 0.5)
    if patch_coordinate > maximum_patch_coordinate:
        return minimum_patch_coordinate
    if patch_coordinate < minimum_patch_coordinate:
        return maximum_patch_coordinate
    return patch_coordinate


__all__ = [
    "SearchExhaustedError",
    "SlumulateStepResult",
    "create_new_households",
    "find_house",
    "forward",
    "move_to_patch",
    "patch_here",
    "patch_here_coordinate",
    "right_turn",
    "settle_households",
    "should_stop",
    "slumulate_step",
    "update_city_income",
    "update_developers",
    "update_households",
    "update_patches",
    "update_time",
    "update_variables",
    "update_availability",
    "update_occupancy",
    "update_rent_payable",
    "update_resicat",
    "update_slum_status",
    "wrap_continuous_coordinate",
]
