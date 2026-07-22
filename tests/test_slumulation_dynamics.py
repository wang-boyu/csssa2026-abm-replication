from __future__ import annotations

import copy
from contextlib import ExitStack
import inspect
import importlib
import math
import random
from statistics import StatisticsError
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import slumulation
from slumulation import constants

BASELINE_SEED = 1729
DYNAMICS_SEED = 20260708
DIFFERENT_DYNAMICS_SEED = 20260709
SOURCE_INCOME_CLASS_VALUES = {"red", "blue", "green"}
FORBIDDEN_PUBLIC_API_NAMES = (
    "Slumulate",
    "slumulate",
    "step",
    "SlumulationModel",
    "SlumulationRunner",
    "SlumulationValidator",
    "SlumulationComparison",
    "SlumulationOutputWriter",
    "OutputWriter",
    "run_slumulation",
    "run_simulation",
    "simulate_slumulation",
    "validate_slumulation",
    "compare_slumulation",
    "write_slumulation_output",
    "write_output",
    "validator",
    "comparison",
    "output_writer",
    "Slumulation",
    "SlumulationStep",
    "MesaModel",
    "MesaSlumulationModel",
    "SlumulationMesaModel",
    "Model",
    "Runner",
    "Validator",
    "Comparison",
    "Simulation",
    "simulation",
)
SETTLEMENT_EXPORTS = (
    "settle_households",
    "find_house",
    "update_occupancy",
    "update_availability",
    "update_slum_status",
    "update_resicat",
    "update_rent_payable",
)
GLOBAL_UPDATE_EXPORTS = (
    "update_city_income",
    "update_variables",
    "update_time",
    "should_stop",
)
SLUMULATE_STEP_EXPORTS = (
    "SlumulateStepResult",
    "slumulate_step",
)


class ScriptedRandom:
    def __init__(
        self,
        values: tuple[float, ...] = (),
        *,
        default: float | None = None,
        reverse_shuffle: bool = False,
    ) -> None:
        self.values = list(values)
        self.default = default
        self.reverse_shuffle = reverse_shuffle
        self.shuffle_calls = 0

    def random(self) -> float:
        if self.values:
            return self.values.pop(0)
        if self.default is not None:
            return self.default
        raise AssertionError("ScriptedRandom ran out of random() values.")

    def uniform(self, lower: float, upper: float) -> float:
        return lower + (upper - lower) * self.random()

    def shuffle(self, values) -> None:
        self.shuffle_calls += 1
        if self.reverse_shuffle:
            values.reverse()

    def sample(self, population, k: int):
        values = list(population)
        self.shuffle(values)
        return values[:k]


def _dynamics_api() -> SimpleNamespace:
    dynamics = importlib.import_module("slumulation.dynamics")

    if not hasattr(dynamics, "create_new_households"):
        raise AssertionError("slumulation.dynamics must expose create_new_households")

    return SimpleNamespace(
        module=dynamics,
        create_new_households=dynamics.create_new_households,
    )


def _settlement_api() -> SimpleNamespace:
    dynamics = importlib.import_module("slumulation.dynamics")

    missing = [name for name in SETTLEMENT_EXPORTS if not hasattr(dynamics, name)]
    if missing:
        raise AssertionError(
            "slumulation.dynamics must expose the bounded "
            f"settlement/search API: missing {missing!r}"
        )

    if not hasattr(slumulation, "settle_households"):
        raise AssertionError("slumulation must re-export settle_households")
    if slumulation.settle_households is not dynamics.settle_households:
        raise AssertionError(
            "slumulation.settle_households must re-export dynamics.settle_households"
        )

    return SimpleNamespace(
        module=dynamics,
        settle_households=dynamics.settle_households,
        find_house=dynamics.find_house,
        update_occupancy=dynamics.update_occupancy,
        update_availability=dynamics.update_availability,
        update_slum_status=dynamics.update_slum_status,
        update_resicat=dynamics.update_resicat,
        update_rent_payable=dynamics.update_rent_payable,
    )


def _household_update_api() -> SimpleNamespace:
    dynamics = importlib.import_module("slumulation.dynamics")

    if not hasattr(dynamics, "update_households"):
        raise AssertionError("slumulation.dynamics must expose update_households")

    return SimpleNamespace(
        module=dynamics,
        update_households=dynamics.update_households,
    )


def _patch_update_api() -> SimpleNamespace:
    dynamics = importlib.import_module("slumulation.dynamics")

    if not hasattr(dynamics, "update_patches"):
        raise AssertionError("slumulation.dynamics must expose update_patches")

    return SimpleNamespace(
        module=dynamics,
        update_patches=dynamics.update_patches,
    )


def _developer_update_api() -> SimpleNamespace:
    dynamics = importlib.import_module("slumulation.dynamics")

    if not hasattr(dynamics, "update_developers"):
        raise AssertionError("slumulation.dynamics must expose update_developers")

    return SimpleNamespace(
        module=dynamics,
        update_developers=dynamics.update_developers,
    )


def _global_update_api() -> SimpleNamespace:
    dynamics = importlib.import_module("slumulation.dynamics")

    missing = [name for name in GLOBAL_UPDATE_EXPORTS if not hasattr(dynamics, name)]
    if missing:
        raise AssertionError(
            "slumulation.dynamics must expose the bounded global "
            f"update API: missing {missing!r}"
        )

    return SimpleNamespace(
        module=dynamics,
        update_city_income=dynamics.update_city_income,
        update_variables=dynamics.update_variables,
        update_time=dynamics.update_time,
        should_stop=dynamics.should_stop,
    )


def _slumulate_step_api() -> SimpleNamespace:
    dynamics = importlib.import_module("slumulation.dynamics")

    missing = [name for name in SLUMULATE_STEP_EXPORTS if not hasattr(dynamics, name)]
    if missing:
        raise AssertionError(
            "slumulation.dynamics must expose the bounded Slumulate "
            f"schedule API: missing {missing!r}"
        )

    return SimpleNamespace(
        module=dynamics,
        SlumulateStepResult=dynamics.SlumulateStepResult,
        slumulate_step=dynamics.slumulate_step,
    )


def _setup_api() -> SimpleNamespace:
    setup = importlib.import_module("slumulation.setup")

    return SimpleNamespace(
        load_setup_parameters=setup.load_setup_parameters,
        setup_initial_world=setup.setup_initial_world,
    )


def _settlement_parameters(**overrides):
    parameter_values = {
        **_typical_run_baseline_combination().parameter_values,
        **overrides,
    }
    return _setup_api().load_setup_parameters(parameter_values)


def _empty_settlement_world():
    return slumulation.build_empty_world()


def _set_heading(household, heading: float) -> None:
    try:
        setattr(household, "heading", heading)
    except AttributeError as exc:
        raise AssertionError(
            "HouseholdState must expose NetLogo-style heading for the bounded "
            "settlement/search movement slice."
        ) from exc


def _searching_household(
    *,
    x: int = 0,
    y: int = 0,
    income_class: str = "red",
    income: float = 100.0,
    willing: bool = True,
    heading: float = 0.0,
):
    household = slumulation.HouseholdState(
        x=x,
        y=y,
        income_class=income_class,
        income=income,
        searching=True,
        willing=willing,
        stay=7,
        num_houses=0,
    )
    _set_heading(household, heading)
    return household


def _resident_household(
    *,
    x: int,
    y: int,
    income_class: str = "red",
    income: float = 100.0,
    willing: bool = True,
):
    household = slumulation.HouseholdState(
        x=x,
        y=y,
        income_class=income_class,
        income=income,
        searching=False,
        willing=willing,
        stay=3,
        num_houses=1,
    )
    _set_heading(household, 0.0)
    return household


def _patch_update_snapshot(patch) -> tuple[object, ...]:
    return (
        patch.rent,
        patch.rent_payable,
        patch.occupied,
        patch.available,
        patch.num_occupants,
        patch.num_units,
        patch.slum,
        patch.slum_occupants,
        patch.resicat,
    )


def _wrap_patch_coordinate(value: int, minimum: int, maximum: int) -> int:
    width = maximum - minimum + 1
    return ((value - minimum) % width) + minimum


def _wrapped_patch_neighbor_coordinates(coordinate):
    x, y = coordinate
    return tuple(
        (
            _wrap_patch_coordinate(
                x + dx,
                constants.WORLD_X_MIN,
                constants.WORLD_X_MAX,
            ),
            _wrap_patch_coordinate(
                y + dy,
                constants.WORLD_Y_MIN,
                constants.WORLD_Y_MAX,
            ),
        )
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
        if dx or dy
    )


def _expected_diffused_rents(world, diffusion_rate: float) -> dict[object, float]:
    old_rents = {coordinate: patch.rent for coordinate, patch in world.patches.items()}

    return {
        coordinate: (1 - diffusion_rate) * old_rent
        + sum(
            diffusion_rate * old_rents[neighbor_coordinate] / 8
            for neighbor_coordinate in _wrapped_patch_neighbor_coordinates(coordinate)
        )
        for coordinate, old_rent in old_rents.items()
    }


def _find_after_one_rejection(api, configure_rejected_patch):
    world = _empty_settlement_world()
    parameters = _settlement_parameters()
    household = _searching_household(income_class="red", income=100.0, heading=0.0)
    world.households.append(household)
    configure_rejected_patch(world, world[(1, 0)], household)

    api.find_house(
        world,
        parameters,
        household,
        ScriptedRandom((0.25, 0.6, 0.75, 0.6)),
        max_search_attempts=2,
    )

    return world, household


def _typical_run_baseline_combination():
    typical_run = constants.SELECTED_EXPERIMENT_REGISTRY["Typical Run"]

    if len(typical_run.parameter_combinations) != 1:
        raise AssertionError("Typical Run must expose exactly one baseline combination")

    return typical_run.parameter_combinations[0]


def _setup_initialization(seed=BASELINE_SEED, parameter_values=None):
    setup_api = _setup_api()
    if parameter_values is None:
        parameter_values = _typical_run_baseline_combination()

    return setup_api.setup_initial_world(parameter_values, seed=seed)


def _new_households_after(
    world,
    before_household_ids: frozenset[int],
):
    return [
        household
        for household in world.households
        if id(household) not in before_household_ids
    ]


def _patch_snapshot(patch) -> tuple[object, ...]:
    return (
        patch.coordinate,
        patch.ward,
        patch.rent,
        patch.rent_payable,
        patch.occupied,
        patch.available,
        patch.num_occupants,
        patch.num_units,
        patch.slum,
        patch.slum_occupants,
        patch.resicat,
    )


def _household_snapshot(household) -> tuple[object, ...]:
    return (
        household.coordinate,
        household.income_class,
        household.income,
        household.informal,
        household.searching,
        household.willing,
        household.class_updated,
        household.old,
        household.stay,
        household.num_houses,
    )


def _developer_snapshot(developer) -> tuple[object, ...]:
    return (
        developer.coordinate,
        developer.no_role,
    )


def _new_household_snapshot(household) -> tuple[object, ...]:
    return (
        household.coordinate,
        household.income,
        household.informal,
        household.income_class,
        household.class_updated,
        household.willing,
        household.searching,
        household.old,
        household.stay,
        household.num_houses,
    )


def _expected_source_crt_count(world, parameters) -> int:
    population = world.summary.population or len(world.households)
    return math.floor((parameters.population_growth_rate * population) / 100)


def _create_new_households(initialization, *, seed=DYNAMICS_SEED):
    dynamics_api = _dynamics_api()
    world = initialization.world
    before_household_ids = frozenset(id(household) for household in world.households)

    dynamics_api.create_new_households(
        world,
        initialization.parameters,
        random.Random(seed),
    )

    return _new_households_after(world, before_household_ids)


def _set_patch_state(world, coordinate, **values):
    patch_state = world[coordinate]
    for name, value in values.items():
        setattr(patch_state, name, value)
    return patch_state


def _global_metric_world():
    world = _empty_settlement_world()
    world.time = 12
    world.city_income = 10_000.0
    for ward in world.summary.ward_slum_pop_percent:
        world.summary.ward_slum_pop_percent[ward] = 0.875

    _set_patch_state(
        world,
        (0, 0),
        rent=90.0,
        rent_payable=30.0,
        occupied=True,
        num_occupants=4,
        slum=True,
        slum_occupants=4,
        resicat=4,
    )
    _set_patch_state(
        world,
        (1, 0),
        rent=60.0,
        rent_payable=18.0,
        occupied=True,
        num_occupants=1,
        resicat=3,
    )
    _set_patch_state(
        world,
        (2, 0),
        rent=70.0,
        rent_payable=22.0,
        occupied=True,
        num_occupants=1,
        resicat=2,
    )
    _set_patch_state(
        world,
        (9, 0),
        rent=100.0,
        rent_payable=40.0,
        occupied=True,
        num_occupants=2,
        slum=True,
        slum_occupants=2,
        resicat=4,
    )
    _set_patch_state(
        world,
        (10, 0),
        rent=80.0,
        rent_payable=44.0,
        occupied=True,
        num_occupants=1,
        resicat=1,
    )
    _set_patch_state(
        world,
        (11, 0),
        rent=75.0,
        rent_payable=26.0,
        occupied=True,
        num_occupants=1,
        resicat=2,
    )

    red_a = _resident_household(x=0, y=0, income_class="red", income=100.0)
    red_b = _resident_household(x=0, y=0, income_class="red", income=110.0)
    blue_a = _resident_household(x=0, y=0, income_class="blue", income=200.0)
    green_a = _resident_household(x=0, y=0, income_class="green", income=300.0)
    red_c = _resident_household(x=1, y=0, income_class="red", income=120.0)
    blue_b = _resident_household(x=2, y=0, income_class="blue", income=220.0)
    red_d = _resident_household(x=9, y=0, income_class="red", income=140.0)
    green_b = _resident_household(x=9, y=0, income_class="green", income=330.0)
    green_c = _resident_household(x=10, y=0, income_class="green", income=360.0)
    blue_c = _resident_household(x=11, y=0, income_class="blue", income=240.0)
    red_a.searching = True
    green_c.searching = True
    world.households.extend(
        [
            red_a,
            red_b,
            blue_a,
            green_a,
            red_c,
            blue_b,
            red_d,
            green_b,
            green_c,
            blue_c,
        ]
    )
    world.developers.extend(
        [
            slumulation.DeveloperState(x=0, y=1, no_role=False),
            slumulation.DeveloperState(x=9, y=1, no_role=True),
        ]
    )
    return world


def _minimal_global_summary_world():
    world = _empty_settlement_world()
    world.city_income = 600.0
    _set_patch_state(
        world,
        (0, 0),
        rent=30.0,
        rent_payable=10.0,
        occupied=True,
        num_occupants=1,
        resicat=3,
    )
    _set_patch_state(
        world,
        (1, 0),
        rent=40.0,
        rent_payable=12.0,
        occupied=True,
        num_occupants=1,
        resicat=2,
    )
    _set_patch_state(
        world,
        (2, 0),
        rent=50.0,
        rent_payable=14.0,
        occupied=True,
        num_occupants=1,
        resicat=1,
    )
    world.households.extend(
        [
            _resident_household(x=0, y=0, income_class="red", income=100.0),
            _resident_household(x=1, y=0, income_class="blue", income=200.0),
            _resident_household(x=2, y=0, income_class="green", income=300.0),
        ]
    )
    return world


class SlumulationSettlementSearchTests(unittest.TestCase):
    def test_settlement_search_api_is_importable_from_dynamics_module(self) -> None:
        api = _settlement_api()

        for name in SETTLEMENT_EXPORTS:
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(api, name)))

    def test_coordinate_lookup_remains_private_implementation_detail(self) -> None:
        api = _settlement_api()
        exported_names = set(getattr(api.module, "__all__", ()))
        reexported_names = set(getattr(slumulation, "__all__", ()))

        for exported_name in exported_names | reexported_names:
            with self.subTest(exported_name=exported_name):
                self.assertNotIn("lookup", exported_name.lower())
                self.assertNotIn("households_by_coordinate", exported_name.lower())

        for private_name in (
            "_HouseholdCoordinateLookup",
            "_households_by_coordinate",
            "_households_here",
        ):
            with self.subTest(private_name=private_name):
                self.assertNotIn(private_name, exported_names)
                self.assertNotIn(private_name, reexported_names)
                self.assertFalse(hasattr(slumulation, private_name))

    def test_find_house_wraps_torus_x_during_forward_movement(self) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        household = _searching_household(x=25, y=0, heading=90.0)
        world.households.append(household)

        api.find_house(
            world,
            _settlement_parameters(),
            household,
            ScriptedRandom((0.0, 0.6)),
            max_search_attempts=1,
        )

        self.assertEqual(household.coordinate, (-25, 0))
        self.assertFalse(household.searching)

    def test_find_house_wraps_torus_y_during_forward_movement(self) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        household = _searching_household(x=0, y=25, heading=0.0)
        world.households.append(household)

        api.find_house(
            world,
            _settlement_parameters(),
            household,
            ScriptedRandom((0.0, 0.6)),
            max_search_attempts=1,
        )

        self.assertEqual(household.coordinate, (0, -25))
        self.assertFalse(household.searching)

    def test_patch_here_maps_continuous_forward_movement_to_patch(self) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        household = _searching_household(x=0, y=0, heading=0.0)
        world.households.append(household)

        api.find_house(
            world,
            _settlement_parameters(),
            household,
            ScriptedRandom((0.25, 0.6)),
            max_search_attempts=1,
        )

        self.assertEqual(household.coordinate, (1, 0))

    def test_settle_households_starts_at_center_without_resetting_heading(self) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        household = _searching_household(x=10, y=10, heading=45.0)
        world.households.append(household)

        api.settle_households(
            world,
            _settlement_parameters(),
            ScriptedRandom((0.125, 0.6)),
            max_search_attempts=1,
        )

        self.assertEqual(household.coordinate, (1, 0))
        self.assertAlmostEqual(household.heading % 360, 90.0)

    def test_settle_households_uses_snapshot_and_random_searcher_order(self) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        first = _searching_household(income_class="red")
        second = _searching_household(income_class="blue")
        late_searcher = _resident_household(x=2, y=0, income_class="green")
        world.households.extend([first, second, late_searcher])
        rng = ScriptedRandom(reverse_shuffle=True)
        calls = []

        def fake_find_house(*args, **kwargs) -> None:
            household = args[2]
            calls.append(household)
            if len(calls) == 1:
                late_searcher.searching = True
            household.searching = False

        with patch.object(api.module, "find_house", side_effect=fake_find_house):
            api.settle_households(
                world,
                _settlement_parameters(),
                rng,
                max_search_attempts=5,
            )

        self.assertGreaterEqual(rng.shuffle_calls, 1)
        self.assertEqual(calls, [second, first])
        self.assertTrue(late_searcher.searching)

    def test_settle_households_successfully_settles_and_updates_destination(
        self,
    ) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        household = _searching_household(
            x=12,
            y=-4,
            income_class="red",
            willing=False,
            heading=0.0,
        )
        world.households.append(household)
        destination = world[(1, 0)]
        destination.rent = 24.0
        destination.rent_payable = 24.0

        api.settle_households(
            world,
            _settlement_parameters(),
            ScriptedRandom((0.25, 0.6)),
            max_search_attempts=1,
        )

        self.assertEqual(household.coordinate, (1, 0))
        self.assertFalse(household.searching)
        self.assertEqual(household.stay, 0)
        self.assertEqual(household.num_houses, 1)
        self.assertTrue(destination.occupied)
        self.assertFalse(destination.available)
        self.assertEqual(destination.num_occupants, 1)
        self.assertFalse(destination.slum)
        self.assertEqual(destination.slum_occupants, 0)
        self.assertEqual(destination.resicat, 3)
        self.assertEqual(destination.rent_payable, 24.0)

    def test_settle_households_leaves_old_patch_state_stale_until_later_update(
        self,
    ) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        old_patch = world[(10, 10)]
        old_patch.num_occupants = 1
        old_patch.occupied = True
        old_patch.available = False
        old_patch.resicat = 3
        old_patch.rent_payable = 12.0
        before_old_patch = _patch_update_snapshot(old_patch)
        household = _searching_household(x=10, y=10, heading=0.0)
        world.households.append(household)

        api.settle_households(
            world,
            _settlement_parameters(),
            ScriptedRandom((0.25, 0.6)),
            max_search_attempts=1,
        )

        self.assertEqual(household.coordinate, (1, 0))
        self.assertEqual(_patch_update_snapshot(old_patch), before_old_patch)

    def test_find_house_rejects_mixed_class_candidate(self) -> None:
        api = _settlement_api()

        def configure(world, patch, household) -> None:
            resident = _resident_household(
                x=patch.x,
                y=patch.y,
                income_class="green",
                willing=True,
            )
            world.households.append(resident)
            patch.available = True
            patch.rent_payable = 0.0

        world, household = _find_after_one_rejection(api, configure)

        self.assertEqual(household.coordinate, (1, 1))
        self.assertEqual(household.num_houses, 2)
        self.assertEqual(world[(1, 1)].num_occupants, 1)

    def test_find_house_rejects_rent_payable_above_income_threshold(self) -> None:
        api = _settlement_api()

        def configure(world, patch, household) -> None:
            patch.available = True
            patch.rent_payable = 30.01

        world, household = _find_after_one_rejection(api, configure)

        self.assertEqual(household.coordinate, (1, 1))
        self.assertEqual(household.num_houses, 2)
        self.assertEqual(world[(1, 1)].num_occupants, 1)

    def test_find_house_allows_rent_payable_equal_to_income_threshold(self) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        household = _searching_household(income=100.0, heading=0.0)
        world.households.append(household)
        world[(1, 0)].rent_payable = 30.0

        api.find_house(
            world,
            _settlement_parameters(),
            household,
            ScriptedRandom((0.25, 0.6)),
            max_search_attempts=1,
        )

        self.assertEqual(household.coordinate, (1, 0))
        self.assertEqual(household.num_houses, 1)

    def test_find_house_rejects_unavailable_candidate(self) -> None:
        api = _settlement_api()

        def configure(world, patch, household) -> None:
            patch.available = False
            patch.rent_payable = 0.0

        world, household = _find_after_one_rejection(api, configure)

        self.assertEqual(household.coordinate, (1, 1))
        self.assertEqual(household.num_houses, 2)
        self.assertEqual(world[(1, 1)].num_occupants, 1)

    def test_find_house_preserves_recursive_unwind_side_effect_count(self) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        parameters = _settlement_parameters()
        household = _searching_household(income=100.0, heading=0.0)
        household.num_houses = 5
        world.households.append(household)
        world[(1, 0)].available = False
        world[(1, 1)].rent_payable = 30.01

        api.find_house(
            world,
            parameters,
            household,
            ScriptedRandom((0.25, 0.6, 0.75, 0.6, 0.75, 0.6)),
            max_search_attempts=3,
        )

        self.assertEqual(household.coordinate, (0, 1))
        self.assertEqual(household.num_houses, 8)
        self.assertFalse(household.searching)

    def test_seeded_find_house_lookup_path_preserves_destination_state(self) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        parameters = _settlement_parameters()
        household = _searching_household(income=100.0, heading=0.0)
        household.num_houses = 5
        world.households.append(household)
        world[(0, 0)].available = False
        destination = world[(-1, -1)]
        destination.rent = 90.0
        destination.num_units = 3

        api.find_house(
            world,
            parameters,
            household,
            random.Random(DIFFERENT_DYNAMICS_SEED),
            max_search_attempts=5,
        )

        self.assertEqual(household.coordinate, (-1, -1))
        self.assertFalse(household.searching)
        self.assertEqual(household.num_houses, 7)
        self.assertTrue(destination.occupied)
        self.assertEqual(destination.num_occupants, 1)
        self.assertTrue(destination.available)
        self.assertFalse(destination.slum)
        self.assertEqual(destination.resicat, 3)
        self.assertEqual(destination.rent_payable, 30.0)

    def test_find_house_success_lookup_is_built_after_candidate_movement(
        self,
    ) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        household = _searching_household(x=10, y=10, income=100.0, heading=0.0)
        world.households.append(household)
        old_patch = world[(10, 10)]
        destination = world[(11, 10)]
        destination.rent = 60.0
        destination.num_units = 2

        api.find_house(
            world,
            _settlement_parameters(),
            household,
            ScriptedRandom((0.25, 0.6)),
            max_search_attempts=1,
        )

        self.assertEqual(household.coordinate, (11, 10))
        self.assertFalse(household.searching)
        self.assertEqual(destination.num_occupants, 1)
        self.assertTrue(destination.occupied)
        self.assertEqual(destination.resicat, 3)
        self.assertEqual(destination.rent_payable, 30.0)
        self.assertFalse(old_patch.occupied)
        self.assertEqual(old_patch.num_occupants, 0)

    def test_find_house_guard_failure_reports_useful_diagnostics(self) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        parameters = _settlement_parameters()
        household = _searching_household(heading=0.0)
        world.households.append(household)
        for patch_state in world.patches.values():
            patch_state.available = False

        with self.assertRaises(Exception) as failure:
            api.find_house(
                world,
                parameters,
                household,
                ScriptedRandom(default=0.0),
                max_search_attempts=3,
            )

        message = str(failure.exception).lower()
        self.assertIn("attempt", message)
        self.assertIn("household", message)
        self.assertTrue("patch" in message or "coordinate" in message)
        self.assertIn("available", message)

    def test_update_occupancy_counts_households_on_patch(self) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        patch_state = world[(2, 2)]
        world.households.extend(
            [
                _resident_household(x=2, y=2),
                _resident_household(x=2, y=2),
                _resident_household(x=3, y=2),
            ]
        )

        api.update_occupancy(world, patch_state)

        self.assertTrue(patch_state.occupied)
        self.assertEqual(patch_state.num_occupants, 2)

    def test_public_patch_helpers_accept_existing_calls_without_lookup(self) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        patch_state = world[(4, 4)]
        patch_state.num_units = 2
        patch_state.available = True
        world.households.append(
            _resident_household(x=4, y=4, income_class="red", willing=False)
        )

        for helper_name in (
            "update_occupancy",
            "update_availability",
            "update_resicat",
        ):
            with self.subTest(helper_name=helper_name):
                inspect.signature(getattr(api, helper_name)).bind(world, patch_state)

        api.update_occupancy(world, patch_state)
        api.update_availability(world, patch_state)
        api.update_resicat(world, patch_state)

        self.assertTrue(patch_state.occupied)
        self.assertEqual(patch_state.num_occupants, 1)
        self.assertFalse(patch_state.available)
        self.assertEqual(patch_state.resicat, 3)

    def test_update_slum_status_sets_and_clears_slum_fields(self) -> None:
        api = _settlement_api()
        patch_state = _empty_settlement_world()[(0, 0)]
        patch_state.num_units = 1
        patch_state.num_occupants = 2

        api.update_slum_status(patch_state)

        self.assertTrue(patch_state.slum)
        self.assertEqual(patch_state.slum_occupants, 2)

        patch_state.num_occupants = 1
        api.update_slum_status(patch_state)

        self.assertFalse(patch_state.slum)
        self.assertEqual(patch_state.slum_occupants, 0)

    def test_update_resicat_tracks_class_slum_and_empty_patch_cases(self) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        patch_state = world[(0, 0)]
        patch_state.num_units = 1
        red = _resident_household(x=0, y=0, income_class="red")
        blue = _resident_household(x=0, y=0, income_class="blue")
        green = _resident_household(x=0, y=0, income_class="green")

        world.households[:] = [red]
        patch_state.num_occupants = 1
        patch_state.slum = False
        api.update_resicat(world, patch_state)
        self.assertEqual(patch_state.resicat, 3)

        world.households[:] = [blue]
        api.update_resicat(world, patch_state)
        self.assertEqual(patch_state.resicat, 2)

        world.households[:] = [green]
        api.update_resicat(world, patch_state)
        self.assertEqual(patch_state.resicat, 1)

        world.households[:] = [red, blue]
        patch_state.num_occupants = 2
        patch_state.slum = True
        api.update_resicat(world, patch_state)
        self.assertEqual(patch_state.resicat, 4)

        world.households.clear()
        patch_state.num_occupants = 0
        api.update_resicat(world, patch_state)
        self.assertEqual(patch_state.resicat, 0)

    def test_update_availability_covers_developer_and_non_developer_branches(
        self,
    ) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        patch_state = world[(0, 0)]
        developer = slumulation.DeveloperState(x=0, y=0)
        world.developers.append(developer)
        patch_state.num_units = 2
        patch_state.num_occupants = 1
        patch_state.available = False

        api.update_availability(world, patch_state)
        self.assertTrue(patch_state.available)

        patch_state.num_occupants = 2
        api.update_availability(world, patch_state)
        self.assertFalse(patch_state.available)

        patch_state.num_occupants = 3
        patch_state.available = True
        api.update_availability(world, patch_state)
        self.assertTrue(patch_state.available)

        world.developers.clear()
        world.households[:] = [_resident_household(x=0, y=0, willing=False)]
        patch_state.num_occupants = 1
        patch_state.available = True
        api.update_availability(world, patch_state)
        self.assertFalse(patch_state.available)

        world.households[:] = [_resident_household(x=0, y=0, willing=True)]
        patch_state.available = False
        api.update_availability(world, patch_state)
        self.assertFalse(patch_state.available)

        world.households.clear()
        patch_state.num_occupants = 0
        patch_state.occupied = True
        patch_state.available = False
        api.update_availability(world, patch_state)
        self.assertFalse(patch_state.occupied)
        self.assertTrue(patch_state.available)

    def test_update_rent_payable_covers_developer_regular_slum_and_politics(
        self,
    ) -> None:
        api = _settlement_api()
        world = _empty_settlement_world()
        patch_state = world[(0, 0)]
        patch_state.rent = 120.0
        patch_state.num_units = 3
        world.developers.append(slumulation.DeveloperState(x=0, y=0))

        api.update_rent_payable(
            world,
            _settlement_parameters(Politics=True),
            patch_state,
        )
        self.assertEqual(patch_state.rent_payable, 40.0)

        world.developers.clear()
        patch_state.slum = False
        patch_state.num_units = 3
        api.update_rent_payable(
            world,
            _settlement_parameters(Politics=True),
            patch_state,
        )
        self.assertEqual(patch_state.rent_payable, 40.0)

        patch_state.slum = True
        patch_state.num_occupants = 4
        api.update_rent_payable(
            world,
            _settlement_parameters(Politics=False),
            patch_state,
        )
        self.assertEqual(patch_state.rent_payable, 30.0)

        world.summary.ward_slum_pop_percent[patch_state.ward] = 0.25
        api.update_rent_payable(
            world,
            _settlement_parameters(Politics=True),
            patch_state,
        )
        self.assertEqual(patch_state.rent_payable, 22.5)


class SlumulationUpdatePatchesTests(unittest.TestCase):
    def test_update_patches_api_is_importable_from_dynamics_module(self) -> None:
        api = _patch_update_api()

        self.assertTrue(callable(api.update_patches))

    def test_update_patches_diffuses_rent_from_snapshot_and_conserves_rent(
        self,
    ) -> None:
        api = _patch_update_api()
        world = _empty_settlement_world()
        world[(0, 0)].rent = 80.0
        world[(1, 0)].rent = 40.0
        diffusion_rate = 0.5
        expected_rents = _expected_diffused_rents(world, diffusion_rate)
        expected_total = sum(expected_rents.values())

        api.update_patches(
            world,
            _settlement_parameters(
                **{"diffusion-rate": diffusion_rate, "economicgrowthrate": 0}
            ),
        )

        self.assertAlmostEqual(
            sum(patch.rent for patch in world.patches.values()),
            expected_total,
        )
        for coordinate, expected_rent in expected_rents.items():
            self.assertAlmostEqual(world[coordinate].rent, expected_rent)

    def test_update_patches_diffuses_rent_across_wrapped_torus_edges(self) -> None:
        api = _patch_update_api()
        world = _empty_settlement_world()
        corner = (constants.WORLD_X_MIN, constants.WORLD_Y_MIN)
        world[corner].rent = 80.0
        diffusion_rate = 0.5

        api.update_patches(
            world,
            _settlement_parameters(
                **{"diffusion-rate": diffusion_rate, "economicgrowthrate": 0}
            ),
        )

        self.assertAlmostEqual(world[corner].rent, 40.0)
        for coordinate in _wrapped_patch_neighbor_coordinates(corner):
            with self.subTest(coordinate=coordinate):
                self.assertAlmostEqual(world[coordinate].rent, 5.0)
        self.assertAlmostEqual(
            sum(patch.rent for patch in world.patches.values()),
            80.0,
        )

    def test_update_patches_grows_rent_after_diffusion(self) -> None:
        api = _patch_update_api()
        world = _empty_settlement_world()
        source_coordinate = (0, 0)
        neighbor_coordinate = (1, 0)
        world[source_coordinate].rent = 200.0
        diffusion_rate = 0.25
        growth_rate = 20
        expected_diffused_rents = _expected_diffused_rents(world, diffusion_rate)
        growth_factor = 1 + ((0.5 * growth_rate) / 100)

        api.update_patches(
            world,
            _settlement_parameters(
                **{
                    "diffusion-rate": diffusion_rate,
                    "economicgrowthrate": growth_rate,
                }
            ),
        )

        self.assertAlmostEqual(
            world[source_coordinate].rent,
            expected_diffused_rents[source_coordinate] * growth_factor,
        )
        self.assertAlmostEqual(
            world[neighbor_coordinate].rent,
            expected_diffused_rents[neighbor_coordinate] * growth_factor,
        )
        self.assertAlmostEqual(
            sum(patch.rent for patch in world.patches.values()),
            sum(expected_diffused_rents.values()) * growth_factor,
        )

    def test_update_patches_calls_patch_helpers_in_source_order(self) -> None:
        api = _patch_update_api()
        world = _empty_settlement_world()
        calls = []
        expected_order = [
            "occupancy",
            "resicat",
            "slum_status",
            "availability",
            "rent_payable",
        ]

        def record_step(name: str, patch_index: int):
            def side_effect(*args):
                patch_state = args[patch_index]
                calls.append((patch_state.coordinate, name))

            return side_effect

        with (
            patch.object(
                api.module,
                "update_occupancy",
                side_effect=record_step("occupancy", 1),
            ),
            patch.object(
                api.module,
                "update_resicat",
                side_effect=record_step("resicat", 1),
            ),
            patch.object(
                api.module,
                "update_slum_status",
                side_effect=record_step("slum_status", 0),
            ),
            patch.object(
                api.module,
                "update_availability",
                side_effect=record_step("availability", 1),
            ),
            patch.object(
                api.module,
                "update_rent_payable",
                side_effect=record_step("rent_payable", 2),
            ),
        ):
            api.update_patches(
                world,
                _settlement_parameters(
                    **{"diffusion-rate": 0, "economicgrowthrate": 0}
                ),
            )

        calls_by_coordinate = {}
        for coordinate, name in calls:
            calls_by_coordinate.setdefault(coordinate, []).append(name)

        self.assertEqual(set(calls_by_coordinate), set(world.patches))
        for names in calls_by_coordinate.values():
            self.assertEqual(names, expected_order)

    def test_update_patches_preserves_resicat_source_order_oddities(self) -> None:
        api = _patch_update_api()
        world = _empty_settlement_world()
        newly_overcrowded = world[(0, 0)]
        newly_overcrowded.num_units = 1
        newly_overcrowded.slum = False
        world.households.extend(
            [
                _resident_household(x=0, y=0, income_class="red"),
                _resident_household(x=0, y=0, income_class="red"),
            ]
        )

        previously_slum = world[(1, 0)]
        previously_slum.num_units = 2
        previously_slum.slum = True
        previously_slum.resicat = 4
        world.households.append(_resident_household(x=1, y=0, income_class="red"))

        api.update_patches(
            world,
            _settlement_parameters(**{"diffusion-rate": 0, "economicgrowthrate": 0}),
        )

        self.assertTrue(newly_overcrowded.slum)
        self.assertEqual(newly_overcrowded.slum_occupants, 2)
        self.assertEqual(newly_overcrowded.resicat, 3)

        self.assertFalse(previously_slum.slum)
        self.assertEqual(previously_slum.slum_occupants, 0)
        self.assertEqual(previously_slum.resicat, 4)

    def test_update_patches_preserves_colocated_household_lookup_semantics(
        self,
    ) -> None:
        api = _patch_update_api()
        parameters = _settlement_parameters(
            **{"diffusion-rate": 0, "economicgrowthrate": 0}
        )
        world = _empty_settlement_world()
        target_coordinate = (4, 4)
        target_patch = world[target_coordinate]
        target_patch.rent = 90.0
        target_patch.num_units = 1
        target_patch.available = True
        world.households.extend(
            [
                _resident_household(
                    x=4,
                    y=4,
                    income_class="red",
                    willing=True,
                ),
                _resident_household(
                    x=4,
                    y=4,
                    income_class="red",
                    willing=False,
                ),
            ]
        )
        expected_world = copy.deepcopy(world)
        expected_patch = expected_world[target_coordinate]

        settlement_api = _settlement_api()
        settlement_api.update_occupancy(expected_world, expected_patch)
        settlement_api.update_resicat(expected_world, expected_patch)
        settlement_api.update_slum_status(expected_patch)
        settlement_api.update_availability(expected_world, expected_patch)
        settlement_api.update_rent_payable(expected_world, parameters, expected_patch)

        api.update_patches(world, parameters)

        self.assertEqual(
            _patch_update_snapshot(world[target_coordinate]),
            _patch_update_snapshot(expected_patch),
        )
        self.assertEqual(target_patch.num_occupants, 2)
        self.assertTrue(target_patch.slum)
        self.assertEqual(target_patch.slum_occupants, 2)
        self.assertEqual(target_patch.resicat, 3)
        self.assertFalse(target_patch.available)
        self.assertEqual(target_patch.rent_payable, 45.0)

    def test_update_patches_exercises_availability_stateful_branches(self) -> None:
        api = _patch_update_api()
        world = _empty_settlement_world()

        developer_under_capacity = world[(0, 0)]
        developer_under_capacity.num_units = 2
        developer_under_capacity.available = False
        world.developers.append(slumulation.DeveloperState(x=0, y=0))
        world.households.append(_resident_household(x=0, y=0, willing=True))

        developer_at_capacity = world[(1, 0)]
        developer_at_capacity.num_units = 1
        developer_at_capacity.available = True
        world.developers.append(slumulation.DeveloperState(x=1, y=0))
        world.households.append(_resident_household(x=1, y=0, willing=True))

        developer_over_capacity = world[(2, 0)]
        developer_over_capacity.num_units = 1
        developer_over_capacity.available = False
        world.developers.append(slumulation.DeveloperState(x=2, y=0))
        world.households.extend(
            [
                _resident_household(x=2, y=0, willing=True),
                _resident_household(x=2, y=0, willing=True),
            ]
        )

        unwilling_occupied = world[(3, 0)]
        unwilling_occupied.num_units = 2
        unwilling_occupied.available = True
        world.households.append(_resident_household(x=3, y=0, willing=False))

        willing_occupied = world[(4, 0)]
        willing_occupied.num_units = 2
        willing_occupied.available = False
        world.households.append(_resident_household(x=4, y=0, willing=True))

        empty_patch = world[(5, 0)]
        empty_patch.occupied = True
        empty_patch.available = False

        api.update_patches(
            world,
            _settlement_parameters(**{"diffusion-rate": 0, "economicgrowthrate": 0}),
        )

        self.assertTrue(developer_under_capacity.available)
        self.assertFalse(developer_at_capacity.available)
        self.assertFalse(developer_over_capacity.available)
        self.assertFalse(unwilling_occupied.available)
        self.assertFalse(willing_occupied.available)
        self.assertFalse(empty_patch.occupied)
        self.assertTrue(empty_patch.available)

    def test_update_patches_sets_rent_payable_for_source_cases(self) -> None:
        api = _patch_update_api()
        world = _empty_settlement_world()

        developer_patch = world[(0, 0)]
        developer_patch.rent = 120.0
        developer_patch.num_units = 3
        world.developers.append(slumulation.DeveloperState(x=0, y=0))

        regular_patch = world[(1, 0)]
        regular_patch.rent = 80.0
        regular_patch.num_units = 4
        world.households.append(_resident_household(x=1, y=0, willing=True))

        slum_patch = world[(2, 0)]
        slum_patch.rent = 90.0
        slum_patch.num_units = 1
        world.households.extend(
            [
                _resident_household(x=2, y=0, willing=True),
                _resident_household(x=2, y=0, willing=True),
                _resident_household(x=2, y=0, willing=True),
            ]
        )
        world.summary.ward_slum_pop_percent[slum_patch.ward] = 0.25

        api.update_patches(
            world,
            _settlement_parameters(
                Politics=True,
                **{"diffusion-rate": 0, "economicgrowthrate": 0},
            ),
        )

        self.assertEqual(developer_patch.rent_payable, 40.0)
        self.assertEqual(regular_patch.rent_payable, 20.0)
        self.assertTrue(slum_patch.slum)
        self.assertEqual(slum_patch.rent_payable, 22.5)

    def test_update_patches_uses_previous_summary_without_refreshing_globals(
        self,
    ) -> None:
        api = _patch_update_api()
        world = _empty_settlement_world()
        world.time = 17
        world.city_income = 12345.0
        slum_patch = world[(0, 0)]
        slum_patch.rent = 90.0
        slum_patch.num_units = 1
        world.households.extend(
            [
                _resident_household(x=0, y=0, willing=True),
                _resident_household(x=0, y=0, willing=True),
                _resident_household(x=0, y=0, willing=True),
            ]
        )
        world.summary.population = 999
        world.summary.slum_pop = 222
        world.summary.avg_income = 123.4
        world.summary.highest_rent = 777.0
        world.summary.lowest_rent = 12.0
        world.summary.ward_slum_pop_percent[slum_patch.ward] = 0.25
        before_summary = copy.deepcopy(world.summary)

        api.update_patches(
            world,
            _settlement_parameters(
                Politics=True,
                **{"diffusion-rate": 0, "economicgrowthrate": 0},
            ),
        )

        self.assertEqual(world.time, 17)
        self.assertEqual(world.city_income, 12345.0)
        self.assertEqual(world.summary, before_summary)
        self.assertEqual(slum_patch.rent_payable, 22.5)
        self.assertFalse(hasattr(world, "validation_outputs"))


class SlumulationUpdateDevelopersTests(unittest.TestCase):
    def test_update_developers_api_is_dynamics_only_and_requires_no_rng(
        self,
    ) -> None:
        api = _developer_update_api()

        self.assertTrue(callable(api.update_developers))
        self.assertEqual(
            tuple(inspect.signature(api.update_developers).parameters),
            ("world",),
        )
        self.assertIn("update_developers", api.module.__all__)
        self.assertFalse(hasattr(slumulation, "update_developers"))

    def test_update_developers_keeps_under_capacity_and_removes_full_patches(
        self,
    ) -> None:
        api = _developer_update_api()
        world = _empty_settlement_world()
        under_capacity = slumulation.DeveloperState(x=0, y=0)
        equal_capacity = slumulation.DeveloperState(x=1, y=0)
        over_capacity = slumulation.DeveloperState(x=2, y=0)
        world.developers.extend([under_capacity, equal_capacity, over_capacity])
        world[(0, 0)].num_units = 2
        world[(0, 0)].num_occupants = 1
        world[(1, 0)].num_units = 1
        world[(1, 0)].num_occupants = 1
        world[(2, 0)].num_units = 1
        world[(2, 0)].num_occupants = 2

        snapshot = api.update_developers(world)

        self.assertEqual(snapshot, (under_capacity, equal_capacity, over_capacity))
        self.assertEqual(world.developers, [under_capacity])
        self.assertFalse(under_capacity.no_role)
        self.assertTrue(equal_capacity.no_role)
        self.assertTrue(over_capacity.no_role)

    def test_update_developers_removes_preexisting_no_role_under_capacity(
        self,
    ) -> None:
        api = _developer_update_api()
        world = _empty_settlement_world()
        stale_no_role = slumulation.DeveloperState(x=0, y=0, no_role=True)
        world.developers.append(stale_no_role)
        world[(0, 0)].num_units = 3
        world[(0, 0)].num_occupants = 1

        api.update_developers(world)

        self.assertEqual(world.developers, [])
        self.assertTrue(stale_no_role.no_role)

    def test_update_developers_uses_outer_ask_start_snapshot_when_removing(
        self,
    ) -> None:
        api = _developer_update_api()
        world = _empty_settlement_world()
        first = slumulation.DeveloperState(x=0, y=0, no_role=True)
        second = slumulation.DeveloperState(x=1, y=0, no_role=True)
        world.developers.extend([first, second])
        world[(0, 0)].num_units = 3
        world[(0, 0)].num_occupants = 1
        world[(1, 0)].num_units = 3
        world[(1, 0)].num_occupants = 1

        api.update_developers(world)

        self.assertEqual(world.developers, [])

    def test_update_developers_nested_check_flags_others_before_current_exit(
        self,
    ) -> None:
        api = _developer_update_api()
        world = _empty_settlement_world()
        first = slumulation.DeveloperState(x=0, y=0, no_role=True)
        flag_events = []

        class TrackingDeveloper(slumulation.DeveloperState):
            def __init__(self, *args, **kwargs) -> None:
                self.no_role_sets = []
                super().__init__(*args, **kwargs)
                self.no_role_sets.clear()

            @property
            def no_role(self) -> bool:
                return self._tracked_no_role

            @no_role.setter
            def no_role(self, value: bool) -> None:
                self._tracked_no_role = value
                if not hasattr(self, "no_role_sets"):
                    return
                self.no_role_sets.append(value)
                if value and not flag_events:
                    flag_events.append(tuple(world.developers))

        second = TrackingDeveloper(x=1, y=0, no_role=False)
        world.developers.extend([first, second])
        world[(0, 0)].num_units = 3
        world[(0, 0)].num_occupants = 1
        world[(1, 0)].num_units = 1
        world[(1, 0)].num_occupants = 1

        api.update_developers(world)

        self.assertTrue(flag_events)
        self.assertIn(first, flag_events[0])
        self.assertIn(second, flag_events[0])
        self.assertEqual(world.developers, [])
        self.assertTrue(second.no_role)

    def test_update_developers_does_not_recompute_patch_or_global_state(
        self,
    ) -> None:
        api = _developer_update_api()
        world = _empty_settlement_world()
        developer = slumulation.DeveloperState(x=0, y=0)
        world.developers.append(developer)
        patch_state = world[(0, 0)]
        patch_state.num_units = 1
        patch_state.num_occupants = 1
        patch_state.occupied = True
        patch_state.available = False
        patch_state.rent_payable = 88.0
        patch_state.resicat = 3
        world.summary.num_developers = 12
        world.city_income = 3456.0
        world.time = 17
        before_patch = _patch_update_snapshot(patch_state)
        before_summary = copy.deepcopy(world.summary)

        api.update_developers(world)

        self.assertEqual(world.developers, [])
        self.assertEqual(_patch_update_snapshot(patch_state), before_patch)
        self.assertEqual(world.summary, before_summary)
        self.assertEqual(world.summary.num_developers, 12)
        self.assertEqual(world.city_income, 3456.0)
        self.assertEqual(world.time, 17)


class SlumulationGlobalUpdateTests(unittest.TestCase):
    def test_global_update_api_is_dynamics_only_and_requires_no_rng(self) -> None:
        api = _global_update_api()
        expected_parameters = {
            "update_city_income": ("world", "parameters"),
            "update_variables": ("world",),
            "update_time": ("world",),
            "should_stop": ("world", "parameters"),
        }

        for name, parameter_names in expected_parameters.items():
            with self.subTest(name=name):
                helper = getattr(api, name)

                self.assertTrue(callable(helper))
                self.assertEqual(
                    tuple(inspect.signature(helper).parameters),
                    parameter_names,
                )
                self.assertIn(name, api.module.__all__)
                self.assertFalse(hasattr(slumulation, name))
                self.assertNotIn(name, getattr(slumulation, "__all__", ()))

    def test_update_city_income_compounds_prior_city_income_only(self) -> None:
        api = _global_update_api()
        world = _empty_settlement_world()
        world.city_income = 800.0
        world.summary.population = 999
        world.summary.avg_income = 123.45
        world.households.extend(
            [
                _resident_household(x=0, y=0, income=1_000.0),
                _resident_household(x=1, y=0, income=2_000.0),
            ]
        )
        before_summary = copy.deepcopy(world.summary)

        api.update_city_income(
            world,
            _settlement_parameters(**{"economicgrowthrate": 12.5}),
        )

        self.assertAlmostEqual(world.city_income, 900.0)
        self.assertNotAlmostEqual(
            world.city_income,
            sum(household.income for household in world.households),
        )
        self.assertEqual(world.summary, before_summary)

    def test_update_variables_refreshes_primary_metrics_from_current_state(
        self,
    ) -> None:
        api = _global_update_api()
        world = _global_metric_world()
        before_patch_snapshots = {
            coordinate: _patch_snapshot(patch)
            for coordinate, patch in world.patches.items()
        }
        before_household_snapshots = tuple(
            _household_snapshot(household) for household in world.households
        )
        before_developer_snapshots = tuple(
            _developer_snapshot(developer) for developer in world.developers
        )

        api.update_variables(world)

        summary = world.summary
        expected_primary_metrics = {
            "slum_pop_percent": 6 / 10,
            "central_slum_pop_percent": (4 / 6) * 100,
            "periphery_slum_pop_percent": (2 / 4) * 100,
            "num_slums": 2,
            "central_num_slums": 1,
            "peripheral_num_slums": 1,
            "slum_area_percent": (2 / 6) * 100,
            "central_slum_area_percent": (1 / 3) * 100,
            "periphery_slum_area_percent": (1 / 3) * 100,
            "slum_density": 6 / 2,
            "central_slum_density": 4 / 1,
            "periphery_slum_density": 2 / 1,
        }
        for field_name, expected_value in expected_primary_metrics.items():
            with self.subTest(field_name=field_name):
                self.assertAlmostEqual(getattr(summary, field_name), expected_value)

        self.assertEqual(summary.red_count, 4)
        self.assertEqual(summary.blue_count, 3)
        self.assertEqual(summary.green_count, 3)
        self.assertAlmostEqual(summary.red_density, 4 / 1)
        self.assertAlmostEqual(summary.blue_density, 3 / 2)
        self.assertAlmostEqual(summary.green_density, 3 / 1)
        self.assertAlmostEqual(summary.avg_density, 10 / 6)
        self.assertAlmostEqual(summary.red_average_rent, (30 + 30 + 18 + 40) / 4)
        self.assertNotAlmostEqual(
            summary.red_average_rent,
            (30 + 18 + 40) / 3,
        )
        self.assertAlmostEqual(summary.blue_average_rent, (30 + 22 + 26) / 3)
        self.assertAlmostEqual(summary.green_average_rent, (30 + 40 + 44) / 3)
        self.assertAlmostEqual(summary.avg_income_red, (100 + 110 + 120 + 140) / 4)
        self.assertAlmostEqual(summary.avg_income_blue, (200 + 220 + 240) / 3)
        self.assertAlmostEqual(summary.avg_income_green, (300 + 330 + 360) / 3)
        self.assertAlmostEqual(summary.avg_income, 10_000 / 10)
        self.assertEqual(summary.num_searching, 2)
        self.assertEqual(summary.population, 10)
        self.assertEqual(summary.slum_pop, 6)
        self.assertEqual(summary.central_slum_pop, 4)
        self.assertEqual(summary.peripheral_slum_pop, 2)
        self.assertEqual(summary.smallest_slum, 2)
        self.assertEqual(summary.largest_slum, 2)
        self.assertNotEqual(summary.largest_slum, 4)
        self.assertEqual(summary.num_developers, 2)
        self.assertEqual(summary.ward_population[5], 6)
        self.assertEqual(summary.ward_population[6], 4)
        self.assertEqual(summary.ward_slum_population[5], 4)
        self.assertEqual(summary.ward_slum_population[6], 2)
        self.assertAlmostEqual(summary.ward_slum_pop_percent[5], 4 / 6)
        self.assertAlmostEqual(summary.ward_slum_pop_percent[6], 2 / 4)
        for ward in (1, 2, 3, 4, 7, 8, 9):
            with self.subTest(stale_ward=ward):
                self.assertEqual(summary.ward_population[ward], 0)
                self.assertEqual(summary.ward_slum_population[ward], 0)
                self.assertAlmostEqual(summary.ward_slum_pop_percent[ward], 0.875)

        self.assertEqual(world.time, 12)
        self.assertEqual(world.city_income, 10_000.0)
        self.assertEqual(
            {
                coordinate: _patch_snapshot(patch)
                for coordinate, patch in world.patches.items()
            },
            before_patch_snapshots,
        )
        self.assertEqual(
            tuple(_household_snapshot(household) for household in world.households),
            before_household_snapshots,
        )
        self.assertEqual(
            tuple(_developer_snapshot(developer) for developer in world.developers),
            before_developer_snapshots,
        )

    def test_update_variables_raises_for_unguarded_empty_class_means(self) -> None:
        api = _global_update_api()
        world = _minimal_global_summary_world()
        world.households[:] = [
            household
            for household in world.households
            if household.income_class != "blue"
        ]

        with self.assertRaises(StatisticsError):
            api.update_variables(world)

    def test_update_variables_raises_for_unguarded_class_density_denominator(
        self,
    ) -> None:
        api = _global_update_api()
        world = _minimal_global_summary_world()
        world[(0, 0)].resicat = 0

        with self.assertRaises(ZeroDivisionError):
            api.update_variables(world)

    def test_update_variables_raises_for_unguarded_avg_density_denominator(
        self,
    ) -> None:
        api = _global_update_api()
        world = _minimal_global_summary_world()
        for patch_state in world.patches.values():
            patch_state.occupied = False
            patch_state.num_occupants = 0

        with self.assertRaises(ZeroDivisionError):
            api.update_variables(world)

    def test_update_variables_raises_for_unguarded_zero_population(self) -> None:
        api = _global_update_api()
        world = _minimal_global_summary_world()
        world.households.clear()

        with self.assertRaises((StatisticsError, ZeroDivisionError)):
            api.update_variables(world)

    def test_update_variables_raises_for_unguarded_central_area_denominator(
        self,
    ) -> None:
        api = _global_update_api()
        world = _empty_settlement_world()
        world.city_income = 600.0
        _set_patch_state(
            world,
            (9, 0),
            rent=30.0,
            rent_payable=10.0,
            occupied=True,
            num_occupants=1,
            resicat=3,
        )
        _set_patch_state(
            world,
            (10, 0),
            rent=40.0,
            rent_payable=12.0,
            occupied=True,
            num_occupants=1,
            resicat=2,
        )
        _set_patch_state(
            world,
            (11, 0),
            rent=50.0,
            rent_payable=14.0,
            occupied=True,
            num_occupants=1,
            resicat=1,
        )
        world.households.extend(
            [
                _resident_household(x=9, y=0, income_class="red", income=100.0),
                _resident_household(x=10, y=0, income_class="blue", income=200.0),
                _resident_household(x=11, y=0, income_class="green", income=300.0),
            ]
        )

        with self.assertRaises(ZeroDivisionError):
            api.update_variables(world)

    def test_update_variables_preserves_stale_guarded_summary_values(self) -> None:
        api = _global_update_api()
        world = _empty_settlement_world()
        world.city_income = 600.0
        stale_values = {
            "periphery_slum_area_percent": 91.0,
            "slum_density": 92.0,
            "smallest_slum": 93,
            "largest_slum": 94,
            "central_slum_density": 95.0,
            "periphery_slum_density": 96.0,
            "periphery_slum_pop_percent": 97.0,
        }
        for field_name, value in stale_values.items():
            setattr(world.summary, field_name, value)
        world.summary.ward_slum_pop_percent[6] = 0.66

        _set_patch_state(
            world,
            (0, 0),
            rent=30.0,
            rent_payable=10.0,
            occupied=True,
            num_occupants=1,
            resicat=3,
        )
        _set_patch_state(
            world,
            (1, 0),
            rent=40.0,
            rent_payable=12.0,
            occupied=True,
            num_occupants=1,
            resicat=2,
        )
        _set_patch_state(
            world,
            (2, 0),
            rent=50.0,
            rent_payable=14.0,
            occupied=True,
            num_occupants=1,
            resicat=1,
        )
        world.households.extend(
            [
                _resident_household(x=0, y=0, income_class="red", income=100.0),
                _resident_household(x=1, y=0, income_class="blue", income=200.0),
                _resident_household(x=2, y=0, income_class="green", income=300.0),
            ]
        )

        api.update_variables(world)

        summary = world.summary
        self.assertEqual(summary.num_slums, 0)
        self.assertEqual(summary.central_num_slums, 0)
        self.assertEqual(summary.peripheral_num_slums, 0)
        self.assertEqual(summary.slum_pop, 0)
        self.assertAlmostEqual(summary.slum_area_percent, 0.0)
        self.assertAlmostEqual(summary.central_slum_area_percent, 0.0)
        for field_name, expected_value in stale_values.items():
            with self.subTest(field_name=field_name):
                self.assertEqual(getattr(summary, field_name), expected_value)
        self.assertAlmostEqual(summary.ward_slum_pop_percent[5], 0.0)
        self.assertAlmostEqual(summary.ward_slum_pop_percent[6], 0.66)
        self.assertAlmostEqual(summary.central_slum_pop_percent, 0.0)

    def test_update_variables_uses_stale_ward5_share_for_central_percent(
        self,
    ) -> None:
        api = _global_update_api()
        world = _empty_settlement_world()
        world.city_income = 600.0
        world.summary.ward_slum_pop_percent[5] = 0.42
        _set_patch_state(world, (0, 0), occupied=True, num_occupants=0)
        _set_patch_state(
            world,
            (9, 0),
            rent=30.0,
            rent_payable=10.0,
            occupied=True,
            num_occupants=1,
            resicat=3,
        )
        _set_patch_state(
            world,
            (10, 0),
            rent=40.0,
            rent_payable=12.0,
            occupied=True,
            num_occupants=1,
            resicat=2,
        )
        _set_patch_state(
            world,
            (11, 0),
            rent=50.0,
            rent_payable=14.0,
            occupied=True,
            num_occupants=1,
            resicat=1,
        )
        world.households.extend(
            [
                _resident_household(x=9, y=0, income_class="red", income=100.0),
                _resident_household(x=10, y=0, income_class="blue", income=200.0),
                _resident_household(x=11, y=0, income_class="green", income=300.0),
            ]
        )

        api.update_variables(world)

        self.assertEqual(world.summary.ward_population[5], 0)
        self.assertAlmostEqual(world.summary.ward_slum_pop_percent[5], 0.42)
        self.assertAlmostEqual(world.summary.central_slum_pop_percent, 42.0)

    def test_update_time_increments_only_world_time(self) -> None:
        api = _global_update_api()
        world = _global_metric_world()
        before_patch_snapshots = {
            coordinate: _patch_snapshot(patch)
            for coordinate, patch in world.patches.items()
        }
        before_household_snapshots = tuple(
            _household_snapshot(household) for household in world.households
        )
        before_developer_snapshots = tuple(
            _developer_snapshot(developer) for developer in world.developers
        )
        before_city_income = world.city_income
        before_summary = copy.deepcopy(world.summary)

        api.update_time(world)

        self.assertEqual(world.time, 13)
        self.assertEqual(world.city_income, before_city_income)
        self.assertEqual(world.summary, before_summary)
        self.assertEqual(
            {
                coordinate: _patch_snapshot(patch)
                for coordinate, patch in world.patches.items()
            },
            before_patch_snapshots,
        )
        self.assertEqual(
            tuple(_household_snapshot(household) for household in world.households),
            before_household_snapshots,
        )
        self.assertEqual(
            tuple(_developer_snapshot(developer) for developer in world.developers),
            before_developer_snapshots,
        )

    def test_should_stop_uses_strict_greater_than_incremented_time(self) -> None:
        api = _global_update_api()
        world = _empty_settlement_world()
        parameters = _settlement_parameters(SimulationRuntime=50)
        world.time = 49

        self.assertFalse(api.should_stop(world, parameters))

        api.update_time(world)
        self.assertEqual(world.time, 50)
        self.assertFalse(api.should_stop(world, parameters))

        api.update_time(world)
        self.assertEqual(world.time, 51)
        self.assertTrue(api.should_stop(world, parameters))


class SlumulationSlumulateStepTests(unittest.TestCase):
    def test_slumulate_step_api_is_dynamics_only(self) -> None:
        api = _slumulate_step_api()

        self.assertTrue(callable(api.slumulate_step))
        self.assertEqual(
            tuple(inspect.signature(api.slumulate_step).parameters),
            ("world", "parameters", "rng"),
        )
        self.assertIn("slumulate_step", api.module.__all__)
        self.assertIn("SlumulateStepResult", api.module.__all__)
        for name in SLUMULATE_STEP_EXPORTS:
            with self.subTest(name=name):
                self.assertFalse(hasattr(slumulation, name))
                self.assertNotIn(name, getattr(slumulation, "__all__", ()))

    def test_slumulate_step_result_exposes_only_stop_and_tick_flags(self) -> None:
        api = _slumulate_step_api()

        result = api.SlumulateStepResult(stopped=True, tick_advanced=False)

        self.assertTrue(result.stopped)
        self.assertFalse(result.tick_advanced)
        self.assertEqual(
            tuple(result.__dataclass_fields__),
            ("stopped", "tick_advanced"),
        )

    def test_slumulate_step_calls_helpers_in_source_order_and_forwards_rng(
        self,
    ) -> None:
        api = _slumulate_step_api()
        world = _empty_settlement_world()
        parameters = _settlement_parameters(SimulationRuntime=50)
        rng = object()
        calls: list[str] = []

        def rng_helper(name: str):
            def helper(passed_world, passed_parameters, passed_rng):
                self.assertIs(passed_world, world)
                self.assertIs(passed_parameters, parameters)
                self.assertIs(passed_rng, rng)
                calls.append(name)

            return helper

        def world_parameters_helper(name: str):
            def helper(passed_world, passed_parameters):
                self.assertIs(passed_world, world)
                self.assertIs(passed_parameters, parameters)
                calls.append(name)

            return helper

        def world_helper(name: str):
            def helper(passed_world):
                self.assertIs(passed_world, world)
                calls.append(name)

            return helper

        def update_time(passed_world):
            self.assertIs(passed_world, world)
            calls.append("update_time")
            passed_world.time += 1

        def should_stop(passed_world, passed_parameters):
            self.assertIs(passed_world, world)
            self.assertIs(passed_parameters, parameters)
            calls.append("should_stop")
            return False

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    api.module,
                    "create_new_households",
                    side_effect=rng_helper("create_new_households"),
                )
            )
            stack.enter_context(
                patch.object(
                    api.module,
                    "settle_households",
                    side_effect=rng_helper("settle_households"),
                )
            )
            stack.enter_context(
                patch.object(
                    api.module,
                    "update_households",
                    side_effect=rng_helper("update_households"),
                )
            )
            stack.enter_context(
                patch.object(
                    api.module,
                    "update_patches",
                    side_effect=world_parameters_helper("update_patches"),
                )
            )
            stack.enter_context(
                patch.object(
                    api.module,
                    "update_developers",
                    side_effect=world_helper("update_developers"),
                )
            )
            stack.enter_context(
                patch.object(
                    api.module,
                    "update_city_income",
                    side_effect=world_parameters_helper("update_city_income"),
                )
            )
            stack.enter_context(
                patch.object(
                    api.module,
                    "update_variables",
                    side_effect=world_helper("update_variables"),
                )
            )
            stack.enter_context(
                patch.object(api.module, "update_time", side_effect=update_time)
            )
            stack.enter_context(
                patch.object(api.module, "should_stop", side_effect=should_stop)
            )

            result = api.slumulate_step(world, parameters, rng)

        self.assertEqual(
            calls,
            [
                "create_new_households",
                "settle_households",
                "update_households",
                "update_patches",
                "update_developers",
                "update_city_income",
                "update_variables",
                "update_time",
                "should_stop",
            ],
        )
        self.assertEqual(world.time, 1)
        self.assertEqual(
            result,
            api.SlumulateStepResult(stopped=False, tick_advanced=True),
        )

    def test_slumulate_step_non_stopped_case_advances_tick_status_only(
        self,
    ) -> None:
        api = _slumulate_step_api()
        world = _empty_settlement_world()
        parameters = _settlement_parameters(SimulationRuntime=50)
        world.time = 49
        rng = random.Random(DYNAMICS_SEED)

        with _patched_slumulate_step_body(api), _forbid_slumulate_step_output_io():
            result = api.slumulate_step(world, parameters, rng)

        self.assertEqual(world.time, 50)
        self.assertFalse(result.stopped)
        self.assertTrue(result.tick_advanced)
        self.assertFalse(hasattr(world, "tick"))

    def test_slumulate_step_stopped_case_stops_before_tick_status(
        self,
    ) -> None:
        api = _slumulate_step_api()
        world = _empty_settlement_world()
        parameters = _settlement_parameters(SimulationRuntime=50)
        world.time = 50
        rng = random.Random(DYNAMICS_SEED)

        with _patched_slumulate_step_body(api), _forbid_slumulate_step_output_io():
            result = api.slumulate_step(world, parameters, rng)

        self.assertEqual(world.time, 51)
        self.assertTrue(result.stopped)
        self.assertFalse(result.tick_advanced)
        self.assertFalse(hasattr(world, "tick"))


def _patched_slumulate_step_body(api: SimpleNamespace) -> ExitStack:
    stack = ExitStack()
    for helper_name in (
        "create_new_households",
        "settle_households",
        "update_households",
        "update_patches",
        "update_developers",
        "update_city_income",
        "update_variables",
    ):
        stack.enter_context(patch.object(api.module, helper_name, return_value=None))
    return stack


def _forbid_slumulate_step_output_io() -> ExitStack:
    stack = ExitStack()
    stack.enter_context(
        patch("builtins.open", side_effect=AssertionError("slumulate_step wrote IO"))
    )
    stack.enter_context(
        patch(
            "pathlib.Path.open",
            side_effect=AssertionError("slumulate_step wrote path IO"),
        )
    )
    return stack


class SlumulationUpdateHouseholdsTests(unittest.TestCase):
    def test_update_households_api_is_importable_from_dynamics_module(self) -> None:
        api = _household_update_api()

        self.assertTrue(callable(api.update_households))

    def test_update_households_uses_snapshot_random_order_and_source_order(
        self,
    ) -> None:
        api = _household_update_api()
        world = _empty_settlement_world()
        first = _resident_household(x=0, y=0, income_class="red", income=100.0)
        second = _resident_household(x=1, y=0, income_class="blue", income=200.0)
        late_household = _resident_household(
            x=2,
            y=0,
            income_class="green",
            income=300.0,
        )
        world.households.extend([first, second])
        rng = ScriptedRandom(reverse_shuffle=True)
        calls = []

        def record_step(name: str, household_index: int):
            def side_effect(*args):
                household = args[household_index]
                calls.append((name, household))
                if name == "income" and household is second:
                    world.households.append(late_household)

            return side_effect

        with (
            patch.object(
                api.module,
                "_update_household_income",
                side_effect=record_step("income", 0),
            ),
            patch.object(
                api.module,
                "_update_household_willingness",
                side_effect=record_step("willingness", 2),
            ),
            patch.object(
                api.module,
                "_update_household_searching",
                side_effect=record_step("searching", 3),
            ),
            patch.object(
                api.module,
                "_update_household_class",
                side_effect=record_step("class", 0),
            ),
            patch.object(
                api.module,
                "_update_household_old",
                side_effect=record_step("old", 0),
            ),
            patch.object(
                api.module,
                "_update_household_stay",
                side_effect=record_step("stay", 0),
            ),
        ):
            updated_households = api.update_households(
                world,
                _settlement_parameters(),
                rng,
            )

        expected_calls = [
            ("income", second),
            ("willingness", second),
            ("searching", second),
            ("class", second),
            ("old", second),
            ("stay", second),
            ("income", first),
            ("willingness", first),
            ("searching", first),
            ("class", first),
            ("old", first),
            ("stay", first),
        ]
        self.assertEqual(rng.shuffle_calls, 1)
        self.assertEqual(updated_households, (second, first))
        self.assertEqual(calls, expected_calls)
        self.assertIn(late_household, world.households)
        self.assertTrue(all(household is not late_household for _, household in calls))

    def test_update_households_income_growth_branches(self) -> None:
        api = _household_update_api()
        world = _empty_settlement_world()
        informal_red = slumulation.HouseholdState(
            x=0,
            y=0,
            income_class="red",
            income=100.0,
            informal=True,
        )
        formal_red = slumulation.HouseholdState(
            x=1,
            y=0,
            income_class="red",
            income=100.0,
            informal=False,
        )
        blue = slumulation.HouseholdState(
            x=2,
            y=0,
            income_class="blue",
            income=100.0,
            informal=True,
        )
        green = slumulation.HouseholdState(
            x=3,
            y=0,
            income_class="green",
            income=100.0,
            informal=False,
        )
        world.households.extend([informal_red, formal_red, blue, green])

        api.update_households(
            world,
            _settlement_parameters(
                Develop=False,
                **{"economicgrowthrate": 10, "staying-power": 10},
            ),
            ScriptedRandom(),
        )

        self.assertAlmostEqual(informal_red.income, 101.0)
        self.assertAlmostEqual(formal_red.income, 110.0)
        self.assertAlmostEqual(blue.income, 110.0)
        self.assertAlmostEqual(green.income, 110.0)

    def test_update_households_willingness_threshold_and_class_override(self) -> None:
        api = _household_update_api()
        world = _empty_settlement_world()
        red_equal = _resident_household(x=0, y=0, income_class="red", income=100.0)
        red_above = _resident_household(x=1, y=0, income_class="red", income=100.0)
        green = _resident_household(x=2, y=0, income_class="green", income=100.0)
        blue = _resident_household(x=3, y=0, income_class="blue", income=100.0)
        for household in (red_equal, red_above, green, blue):
            household.willing = True
        world.households.extend([red_equal, red_above, green, blue])
        world[(0, 0)].rent_payable = 30.0
        world[(1, 0)].rent_payable = 30.01
        world[(2, 0)].rent_payable = 90.0
        world[(3, 0)].rent_payable = 90.0

        api.update_households(
            world,
            _settlement_parameters(
                Develop=False,
                **{
                    "economicgrowthrate": 0,
                    "price-sensitivity": 0,
                    "staying-power": 10,
                },
            ),
            ScriptedRandom(),
        )

        self.assertFalse(red_equal.willing)
        self.assertTrue(red_above.willing)
        self.assertFalse(green.willing)
        self.assertFalse(blue.willing)

    def test_update_households_searching_rent_pressure_mixed_class_and_developer(
        self,
    ) -> None:
        api = _household_update_api()
        world = _empty_settlement_world()
        solo = _resident_household(x=0, y=0, income_class="red", income=100.0)
        mixed_red = _resident_household(x=1, y=0, income_class="red", income=100.0)
        mixed_blue = _resident_household(x=1, y=0, income_class="blue", income=100.0)
        world.households.extend([solo, mixed_red, mixed_blue])
        rent_pressure_patch = world[(0, 0)]
        rent_pressure_patch.rent_payable = 31.0
        rent_pressure_patch.num_units = 4
        rent_pressure_patch.available = False
        rent_pressure_patch.resicat = 3
        world[(1, 0)].rent_payable = 0.0

        api.update_households(
            world,
            _settlement_parameters(
                Develop=True,
                **{
                    "economicgrowthrate": 0,
                    "price-sensitivity": 0,
                    "staying-power": 0,
                },
            ),
            ScriptedRandom((0.67,)),
        )

        self.assertTrue(solo.searching)
        self.assertTrue(mixed_red.searching)
        self.assertTrue(mixed_blue.searching)
        self.assertEqual(len(world.developers), 1)
        self.assertEqual(world.developers[0].coordinate, (0, 0))
        self.assertFalse(world.developers[0].no_role)
        self.assertEqual(rent_pressure_patch.num_units, 6)
        self.assertTrue(rent_pressure_patch.available)
        self.assertEqual(rent_pressure_patch.resicat, 0)
        self.assertFalse(
            any(developer.coordinate == (1, 0) for developer in world.developers)
        )

    def test_update_households_searching_rent_pressure_equality_does_not_hatch(
        self,
    ) -> None:
        api = _household_update_api()
        world = _empty_settlement_world()
        household = _resident_household(x=0, y=0, income_class="red", income=100.0)
        world.households.append(household)
        patch_state = world[(0, 0)]
        patch_state.rent_payable = 60.0
        patch_state.num_units = 4
        patch_state.available = False
        patch_state.resicat = 3
        rng = ScriptedRandom((0.42,))

        api.update_households(
            world,
            _settlement_parameters(
                Develop=True,
                **{
                    "economicgrowthrate": 0,
                    "price-sensitivity": 0,
                    "staying-power": 1,
                },
            ),
            rng,
        )

        self.assertFalse(household.searching)
        self.assertEqual(world.developers, [])
        self.assertEqual(rng.values, [0.42])
        self.assertEqual(patch_state.num_units, 4)
        self.assertFalse(patch_state.available)
        self.assertEqual(patch_state.resicat, 3)

    def test_update_households_developer_guards_and_hatch_unit_draws(self) -> None:
        api = _household_update_api()

        def run_case(
            *,
            develop: bool = True,
            existing_developer: bool = False,
            colocated_household: bool = False,
            random_values: tuple[float, ...] = (),
        ):
            world = _empty_settlement_world()
            household = _resident_household(
                x=0,
                y=0,
                income_class="red",
                income=100.0,
            )
            world.households.append(household)
            if colocated_household:
                world.households.append(
                    _resident_household(
                        x=0,
                        y=0,
                        income_class="red",
                        income=100.0,
                    )
                )
            if existing_developer:
                world.developers.append(slumulation.DeveloperState(x=0, y=0))

            patch_state = world[(0, 0)]
            patch_state.rent_payable = 31.0
            patch_state.num_units = 4
            patch_state.available = False
            patch_state.resicat = 3
            rng = ScriptedRandom(random_values)

            api.update_households(
                world,
                _settlement_parameters(
                    Develop=develop,
                    **{
                        "economicgrowthrate": 0,
                        "price-sensitivity": 0,
                        "staying-power": 0,
                    },
                ),
                rng,
            )

            return world, patch_state, rng

        guard_cases = (
            ("develop false", {"develop": False}, 0),
            ("existing developer", {"existing_developer": True}, 1),
            ("co-located household", {"colocated_household": True}, 0),
        )
        for name, options, expected_developer_count in guard_cases:
            with self.subTest(name=name):
                world, patch_state, _rng = run_case(**options)

                self.assertEqual(len(world.developers), expected_developer_count)
                self.assertEqual(patch_state.num_units, 4)
                self.assertFalse(patch_state.available)
                self.assertEqual(patch_state.resicat, 3)

        for draw, expected_increment in ((0.0, 0), (0.99, 2)):
            with self.subTest(draw=draw):
                world, patch_state, rng = run_case(random_values=(draw,))

                self.assertEqual(len(world.developers), 1)
                self.assertEqual(world.developers[0].coordinate, (0, 0))
                self.assertFalse(world.developers[0].no_role)
                self.assertEqual(patch_state.num_units, 4 + expected_increment)
                self.assertTrue(patch_state.available)
                self.assertEqual(patch_state.resicat, 0)
                self.assertEqual(rng.values, [])

    def test_update_households_dynamic_class_thresholds_use_current_incomes(
        self,
    ) -> None:
        api = _household_update_api()
        world = _empty_settlement_world()
        target = slumulation.HouseholdState(
            x=0,
            y=0,
            income_class="red",
            income=10.0,
            informal=False,
        )
        middle = slumulation.HouseholdState(
            x=1,
            y=0,
            income_class="red",
            income=10.0,
            informal=False,
        )
        first = slumulation.HouseholdState(
            x=2,
            y=0,
            income_class="red",
            income=10.0,
            informal=True,
        )
        world.households.extend([target, middle, first])

        api.update_households(
            world,
            _settlement_parameters(
                Develop=False,
                **{"economicgrowthrate": 100, "staying-power": 10},
            ),
            ScriptedRandom(reverse_shuffle=True),
        )

        self.assertAlmostEqual(first.income, 11.0)
        self.assertAlmostEqual(middle.income, 20.0)
        self.assertAlmostEqual(target.income, 20.0)
        self.assertEqual(first.income_class, "green")
        self.assertEqual(middle.income_class, "green")
        self.assertEqual(target.income_class, "blue")
        self.assertTrue(first.class_updated)
        self.assertTrue(middle.class_updated)
        self.assertTrue(target.class_updated)

    def test_update_households_class_equality_preserves_class_and_increments_age(
        self,
    ) -> None:
        api = _household_update_api()
        world = _empty_settlement_world()
        household_without_prior_update = slumulation.HouseholdState(
            x=0,
            y=0,
            income_class="green",
            income=100.0,
            class_updated=False,
            old=7,
            stay=9,
        )
        household_with_prior_update = slumulation.HouseholdState(
            x=1,
            y=0,
            income_class="green",
            income=100.0,
            class_updated=True,
            old=2,
            stay=4,
        )
        world.households.extend(
            [household_without_prior_update, household_with_prior_update]
        )

        api.update_households(
            world,
            _settlement_parameters(
                Develop=False,
                **{
                    "economicgrowthrate": 0,
                    "price-sensitivity": 0,
                    "staying-power": 10,
                },
            ),
            ScriptedRandom(),
        )

        self.assertEqual(household_without_prior_update.income_class, "green")
        self.assertFalse(household_without_prior_update.class_updated)
        self.assertEqual(household_without_prior_update.old, 8)
        self.assertEqual(household_without_prior_update.stay, 10)
        self.assertEqual(household_with_prior_update.income_class, "green")
        self.assertTrue(household_with_prior_update.class_updated)
        self.assertEqual(household_with_prior_update.old, 3)
        self.assertEqual(household_with_prior_update.stay, 5)


class SlumulationCreateNewHouseholdsTests(unittest.TestCase):
    def test_create_new_households_is_importable_from_dynamics_module(self) -> None:
        api = _dynamics_api()

        self.assertTrue(callable(api.create_new_households))

    def test_create_new_households_adds_source_floor_count_for_baseline(self) -> None:
        initialization = _setup_initialization()
        world = initialization.world
        original_household_count = len(world.households)
        expected_new_count = _expected_source_crt_count(
            world, initialization.parameters
        )

        new_households = _create_new_households(initialization)

        self.assertEqual(original_household_count, 361)
        self.assertEqual(initialization.parameters.population_growth_rate, 3)
        self.assertEqual(expected_new_count, 10)
        self.assertEqual(len(new_households), expected_new_count)
        self.assertEqual(len(world.households), original_household_count + 10)

    def test_create_new_households_does_not_move_existing_households(self) -> None:
        initialization = _setup_initialization()
        world = initialization.world
        before_household_snapshots = {
            id(household): _household_snapshot(household)
            for household in world.households
        }

        _create_new_households(initialization)

        for household in world.households:
            before_snapshot = before_household_snapshots.get(id(household))
            if before_snapshot is None:
                continue

            with self.subTest(coordinate=household.coordinate):
                self.assertEqual(_household_snapshot(household), before_snapshot)

    def test_create_new_households_does_not_update_patch_state_or_settle(self) -> None:
        initialization = _setup_initialization()
        world = initialization.world
        before_patch_snapshots = {
            coordinate: _patch_snapshot(patch)
            for coordinate, patch in world.patches.items()
        }

        new_households = _create_new_households(initialization)

        self.assertTrue(new_households)
        for coordinate, patch_state in world.patches.items():
            with self.subTest(coordinate=coordinate):
                self.assertEqual(
                    _patch_snapshot(patch_state), before_patch_snapshots[coordinate]
                )

    def test_new_households_start_at_source_default_center(self) -> None:
        initialization = _setup_initialization()

        new_households = _create_new_households(initialization)

        self.assertTrue(new_households)
        self.assertTrue(
            all(household.coordinate == (0, 0) for household in new_households)
        )

    def test_new_households_receive_source_initial_fields(self) -> None:
        initialization = _setup_initialization()

        new_households = _create_new_households(initialization)

        self.assertTrue(new_households)
        for household in new_households:
            with self.subTest(income=household.income):
                self.assertGreater(household.income, 0)
                self.assertIn(household.income_class, SOURCE_INCOME_CLASS_VALUES)
                self.assertTrue(household.class_updated)
                self.assertTrue(household.searching)
                self.assertEqual(household.old, 0)
                self.assertEqual(household.stay, 0)
                self.assertEqual(household.num_houses, 0)

    def test_new_household_willingness_follows_source_rule(self) -> None:
        initialization = _setup_initialization()
        world = initialization.world
        parameters = initialization.parameters
        center_patch = world.patches[(0, 0)]

        new_households = _create_new_households(initialization)

        self.assertTrue(new_households)
        for household in new_households:
            with self.subTest(
                income=household.income, income_class=household.income_class
            ):
                source_rule_willing = (
                    center_patch.rent_payable
                    > (1 - parameters.price_sensitivity) * 0.3 * household.income
                )
                expected_willing = (
                    source_rule_willing and household.income_class == "red"
                )

                self.assertEqual(household.willing, expected_willing)
                if household.income_class in {"green", "blue"}:
                    self.assertFalse(household.willing)

    def test_new_household_draws_are_deterministic_for_same_local_seed(self) -> None:
        first_initialization = _setup_initialization()
        second_initialization = _setup_initialization()

        first_new_households = _create_new_households(
            first_initialization,
            seed=DYNAMICS_SEED,
        )
        second_new_households = _create_new_households(
            second_initialization,
            seed=DYNAMICS_SEED,
        )

        self.assertEqual(
            tuple(
                _new_household_snapshot(household) for household in first_new_households
            ),
            tuple(
                _new_household_snapshot(household)
                for household in second_new_households
            ),
        )

    def test_new_household_draws_can_change_with_different_local_seed(self) -> None:
        first_initialization = _setup_initialization()
        second_initialization = _setup_initialization()

        first_new_households = _create_new_households(
            first_initialization,
            seed=DYNAMICS_SEED,
        )
        second_new_households = _create_new_households(
            second_initialization,
            seed=DIFFERENT_DYNAMICS_SEED,
        )

        self.assertNotEqual(
            tuple(
                _new_household_snapshot(household) for household in first_new_households
            ),
            tuple(
                _new_household_snapshot(household)
                for household in second_new_households
            ),
        )

    def test_new_household_informality_uses_informality_index(self) -> None:
        all_formal_parameters = {
            **_typical_run_baseline_combination().parameter_values,
            "informalityindex": 0,
        }
        all_informal_parameters = {
            **_typical_run_baseline_combination().parameter_values,
            "informalityindex": 1,
        }

        formal_initialization = _setup_initialization(
            parameter_values=all_formal_parameters
        )
        informal_initialization = _setup_initialization(
            parameter_values=all_informal_parameters
        )

        formal_new_households = _create_new_households(formal_initialization)
        informal_new_households = _create_new_households(informal_initialization)

        self.assertTrue(formal_new_households)
        self.assertTrue(informal_new_households)
        self.assertTrue(
            all(not household.informal for household in formal_new_households)
        )
        self.assertTrue(
            all(household.informal for household in informal_new_households)
        )

    def test_create_new_households_does_not_change_time(self) -> None:
        initialization = _setup_initialization()
        world = initialization.world
        before_time = world.time

        _create_new_households(initialization)

        self.assertEqual(world.time, before_time)

    def test_dynamics_slice_does_not_publish_simulation_or_output_apis(self) -> None:
        api = _dynamics_api()
        world = _setup_initialization().world
        namespaces = (
            ("slumulation", slumulation),
            ("slumulation.dynamics", api.module),
            ("WorldState", world),
        )

        for namespace_name, namespace in namespaces:
            exported_names = set(getattr(namespace, "__all__", ()))
            for api_name in FORBIDDEN_PUBLIC_API_NAMES:
                with self.subTest(namespace=namespace_name, api_name=api_name):
                    self.assertFalse(hasattr(namespace, api_name), api_name)
                    self.assertNotIn(api_name, exported_names)


if __name__ == "__main__":
    unittest.main()
