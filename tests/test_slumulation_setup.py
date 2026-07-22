from __future__ import annotations

from collections import Counter
import importlib
import math
import random
from types import SimpleNamespace
import unittest

import slumulation
from slumulation import constants

BASELINE_SEED = 1729
DIFFERENT_SEED = 1730
SOURCE_INITIAL_MAX_RENT = 1000
SOURCE_INCOME_CLASS_VALUES = {"red", "blue", "green"}
SOURCE_RESICAT_BY_CLASS = {
    "green": 1,
    "blue": 2,
    "red": 3,
}
EXPECTED_BASELINE_PARAMETERS = {
    "staying-power": 0.3,
    "percent-inappropriate-land": 10,
    "informalityindex": 0.7,
    "percent-prime-land": 10,
    "initialcitylimit": 9,
    "popgrowthrate": 3,
    "SimulationRuntime": 50,
    "Politics": True,
    "Develop": True,
    "price-sensitivity": 0.1,
    "diffusion-rate": 0.03,
    "economicgrowthrate": 2,
    "initialinequality": 10,
}
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
    "output_writer",
)


def _setup_api() -> SimpleNamespace:
    setup = importlib.import_module("slumulation.setup")

    expected_exports = ("load_setup_parameters", "setup_initial_world")

    for name in expected_exports:
        if not hasattr(setup, name):
            raise AssertionError(f"slumulation.setup must export {name}")

        if not hasattr(slumulation, name):
            raise AssertionError(f"slumulation must re-export {name}")

        if getattr(slumulation, name) is not getattr(setup, name):
            raise AssertionError(f"slumulation.{name} must re-export setup.{name}")

    return SimpleNamespace(
        module=setup,
        load_setup_parameters=setup.load_setup_parameters,
        setup_initial_world=setup.setup_initial_world,
    )


def _typical_run_baseline_combination():
    typical_run = constants.SELECTED_EXPERIMENT_REGISTRY["Typical Run"]

    if len(typical_run.parameter_combinations) != 1:
        raise AssertionError("Typical Run must expose exactly one baseline combination")

    return typical_run.parameter_combinations[0]


def _typical_run_baseline_parameters() -> dict[str, object]:
    return _typical_run_baseline_combination().parameter_values


def _setup_initialization(api, seed=BASELINE_SEED, parameter_values=None):
    if parameter_values is None:
        parameter_values = _typical_run_baseline_combination()

    return api.setup_initial_world(parameter_values, seed=seed)


def _initialized_world(initialization):
    if hasattr(initialization, "world"):
        return initialization.world

    return initialization


def _strict_city_core_coordinates(
    initial_city_limit: int,
) -> frozenset[tuple[int, int]]:
    return frozenset(
        coordinate
        for coordinate in _all_world_coordinates()
        if abs(coordinate[0]) < initial_city_limit
        and abs(coordinate[1]) < initial_city_limit
    )


def _inclusive_city_core_coordinates(
    initial_city_limit: int,
) -> frozenset[tuple[int, int]]:
    return frozenset(
        coordinate
        for coordinate in _all_world_coordinates()
        if abs(coordinate[0]) <= initial_city_limit
        and abs(coordinate[1]) <= initial_city_limit
    )


def _all_world_coordinates() -> tuple[tuple[int, int], ...]:
    return tuple(
        (x, y)
        for x in range(constants.WORLD_X_MIN, constants.WORLD_X_MAX + 1)
        for y in range(constants.WORLD_Y_MIN, constants.WORLD_Y_MAX + 1)
    )


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


def _world_snapshot(world) -> tuple[tuple[object, ...], tuple[object, ...]]:
    return (
        tuple(_patch_snapshot(patch) for _, patch in sorted(world.patches.items())),
        tuple(
            _household_snapshot(household)
            for household in sorted(world.households, key=lambda item: item.coordinate)
        ),
    )


def _households_by_coordinate(world) -> dict[tuple[int, int], list]:
    households_by_coordinate: dict[tuple[int, int], list] = {}

    for household in world.households:
        households_by_coordinate.setdefault(household.coordinate, []).append(household)

    return households_by_coordinate


def _sample_standard_deviation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0

    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _source_income_class_thresholds(world) -> tuple[float, float, float, float]:
    incomes = [household.income for household in world.households]
    mean_income = sum(incomes) / len(incomes)
    sample_standard_deviation = _sample_standard_deviation(incomes)

    return (
        mean_income,
        sample_standard_deviation,
        mean_income - 0.1 * sample_standard_deviation,
        mean_income + 1.1 * sample_standard_deviation,
    )


def _source_income_class_for(
    income: float,
    red_threshold: float,
    green_threshold: float,
) -> str | None:
    if income > green_threshold:
        return "green"
    if income < red_threshold:
        return "red"
    if income < green_threshold and income > red_threshold:
        return "blue"
    return None


_MISSING = object()


def _name_variants(*names: str) -> tuple[str, ...]:
    variants: list[str] = []
    for name in names:
        for variant in (
            name,
            name.replace("-", "_"),
            name.replace("_", "-"),
        ):
            if variant not in variants:
                variants.append(variant)
    return tuple(variants)


def _summary_containers(initialization) -> tuple[object, ...]:
    world = _initialized_world(initialization)
    containers: list[object] = [initialization, world]

    for parent in (initialization, world):
        for name in ("summary", "metrics", "global_variables", "globals"):
            nested = getattr(parent, name, None)
            if nested is not None and nested not in containers:
                containers.append(nested)

    return tuple(containers)


def _summary_value(initialization, *names: str):
    value = _maybe_summary_value(initialization, *names)
    if value is _MISSING:
        aliases = ", ".join(_name_variants(*names))
        raise AssertionError(f"Missing setup summary value for any of: {aliases}")
    return value


def _maybe_summary_value(initialization, *names: str):
    for container in _summary_containers(initialization):
        for name in _name_variants(*names):
            if isinstance(container, dict) and name in container:
                return container[name]
            if hasattr(container, name):
                return getattr(container, name)
    return _MISSING


def _ward_summary_values(
    initialization, *mapping_names: str, stem: str
) -> dict[int, float]:
    mapping = _maybe_summary_value(initialization, *mapping_names)
    if mapping is not _MISSING:
        return {
            ward: mapping[ward] if ward in mapping else mapping[str(ward)]
            for ward in range(1, 10)
        }

    values: dict[int, float] = {}
    for ward in range(1, 10):
        values[ward] = _summary_value(
            initialization,
            f"ward{ward}{stem}",
            f"ward_{ward}_{stem}",
            f"ward{ward}_{stem}",
        )
    return values


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _household_patch_rent_payables(world, income_class: str) -> list[float]:
    return [
        world.patches[household.coordinate].rent_payable
        for household in world.households
        if household.income_class == income_class
    ]


def _expected_ward_patch_sums(world, attribute: str) -> dict[int, int]:
    return {
        ward: sum(
            getattr(patch, attribute)
            for patch in world.patches.values()
            if patch.ward == ward
        )
        for ward in range(1, 10)
    }


class SlumulationSetupTests(unittest.TestCase):
    def test_default_parameters_load_typical_run_baseline_combination(self) -> None:
        api = _setup_api()
        baseline_combination = _typical_run_baseline_combination()
        baseline_parameters = _typical_run_baseline_parameters()

        self.assertEqual(baseline_parameters, EXPECTED_BASELINE_PARAMETERS)

        default_parameters = api.load_setup_parameters()
        registry_parameters = api.load_setup_parameters(baseline_combination)
        explicit_parameters = api.load_setup_parameters(baseline_parameters)

        self.assertEqual(default_parameters.parameter_values, baseline_parameters)
        self.assertEqual(registry_parameters.parameter_values, baseline_parameters)
        self.assertEqual(explicit_parameters.parameter_values, baseline_parameters)

    def test_city_core_coordinate_counts_match_source_setup_predicates(self) -> None:
        baseline_parameters = _typical_run_baseline_parameters()
        initial_city_limit = baseline_parameters["initialcitylimit"]

        strict_city_core = _strict_city_core_coordinates(initial_city_limit)
        inclusive_city_core = _inclusive_city_core_coordinates(initial_city_limit)

        self.assertEqual(len(strict_city_core), 289)
        self.assertEqual(len(inclusive_city_core), 361)
        self.assertTrue(strict_city_core < inclusive_city_core)

    def test_baseline_selected_prime_and_inappropriate_draw_count_is_65(self) -> None:
        api = _setup_api()
        baseline_parameters = _typical_run_baseline_parameters()
        initial_city_limit = baseline_parameters["initialcitylimit"]
        min_rent = SOURCE_INITIAL_MAX_RENT / baseline_parameters["initialinequality"]
        selected_rents = {min_rent, SOURCE_INITIAL_MAX_RENT}

        initialization = _setup_initialization(api)
        world = _initialized_world(initialization)
        selected_coordinates = getattr(initialization, "selected_coordinates", None)
        prime_coordinates = getattr(initialization, "prime_coordinates", ())
        inappropriate_coordinates = getattr(
            initialization,
            "inappropriate_coordinates",
            (),
        )

        if selected_coordinates is None:
            selected_coordinates = tuple(
                patch.coordinate
                for patch in world.patches.values()
                if patch.rent in selected_rents
            )

        self.assertEqual(len(selected_coordinates), 65)
        self.assertEqual(
            set(selected_coordinates),
            set(prime_coordinates) | set(inappropriate_coordinates),
        )
        self.assertTrue(
            all(
                coordinate in _strict_city_core_coordinates(initial_city_limit)
                for coordinate in selected_coordinates
            )
        )
        self.assertTrue(
            all(
                world.patches[coordinate].rent == SOURCE_INITIAL_MAX_RENT
                for coordinate in prime_coordinates
            )
        )
        self.assertTrue(
            all(
                world.patches[coordinate].rent == min_rent
                for coordinate in inappropriate_coordinates
            )
        )

    def test_remaining_city_core_rents_preserve_source_no_min_rent_offset(
        self,
    ) -> None:
        api = _setup_api()
        initialization = _setup_initialization(api)
        max_rent = getattr(initialization, "max_rent", SOURCE_INITIAL_MAX_RENT)
        min_rent = getattr(
            initialization,
            "min_rent",
            SOURCE_INITIAL_MAX_RENT
            / _typical_run_baseline_parameters()["initialinequality"],
        )
        remaining_coordinates = getattr(initialization, "remaining_coordinates")
        world = _initialized_world(initialization)
        remaining_rents = [
            world.patches[coordinate].rent for coordinate in remaining_coordinates
        ]

        self.assertEqual(len(remaining_rents), 296)
        self.assertTrue(
            all(0 <= rent < max_rent - min_rent for rent in remaining_rents)
        )
        self.assertLess(min(remaining_rents), min_rent)

    def test_baseline_world_places_one_household_on_each_inclusive_core_patch(
        self,
    ) -> None:
        api = _setup_api()
        initial_city_limit = _typical_run_baseline_parameters()["initialcitylimit"]
        inclusive_city_core = _inclusive_city_core_coordinates(initial_city_limit)

        world = _initialized_world(_setup_initialization(api))
        coordinate_counts = Counter(
            household.coordinate for household in world.households
        )

        self.assertEqual(len(world.households), 361)
        self.assertEqual(set(coordinate_counts), inclusive_city_core)
        self.assertTrue(all(count == 1 for count in coordinate_counts.values()))

        for coordinate, patch in world.patches.items():
            with self.subTest(coordinate=coordinate):
                self.assertEqual(patch.num_units, 1)
                if coordinate in inclusive_city_core:
                    self.assertTrue(patch.occupied)
                    self.assertEqual(patch.num_occupants, 1)
                else:
                    self.assertFalse(patch.occupied)
                    self.assertEqual(patch.num_occupants, 0)

    def test_no_households_exist_outside_inclusive_city_core(self) -> None:
        api = _setup_api()
        initial_city_limit = _typical_run_baseline_parameters()["initialcitylimit"]
        inclusive_city_core = _inclusive_city_core_coordinates(initial_city_limit)

        world = _initialized_world(_setup_initialization(api))
        outside_households = [
            household
            for household in world.households
            if household.coordinate not in inclusive_city_core
        ]

        self.assertEqual(outside_households, [])

    def test_rent_payable_equals_rent_after_setup_initialization(self) -> None:
        api = _setup_api()

        world = _initialized_world(_setup_initialization(api))

        for coordinate, patch in world.patches.items():
            with self.subTest(coordinate=coordinate):
                self.assertEqual(patch.rent_payable, patch.rent)

    def test_non_city_core_patches_keep_default_rent_and_no_occupants(self) -> None:
        api = _setup_api()
        initial_city_limit = _typical_run_baseline_parameters()["initialcitylimit"]
        inclusive_city_core = _inclusive_city_core_coordinates(initial_city_limit)

        world = _initialized_world(_setup_initialization(api))

        for coordinate, patch in world.patches.items():
            if coordinate in inclusive_city_core:
                continue

            with self.subTest(coordinate=coordinate):
                self.assertEqual(patch.rent, 0)
                self.assertEqual(patch.rent_payable, 0)
                self.assertFalse(patch.occupied)
                self.assertTrue(patch.available)
                self.assertEqual(patch.num_occupants, 0)
                self.assertEqual(patch.num_units, 1)
                self.assertFalse(patch.slum)
                self.assertEqual(patch.slum_occupants, 0)
                self.assertEqual(patch.resicat, 0)

    def test_setup_is_deterministic_for_same_seed(self) -> None:
        api = _setup_api()

        first_world = _initialized_world(_setup_initialization(api, seed=BASELINE_SEED))
        second_world = _initialized_world(
            _setup_initialization(api, seed=BASELINE_SEED)
        )

        self.assertEqual(_world_snapshot(first_world), _world_snapshot(second_world))

    def test_setup_requires_explicit_non_none_seed(self) -> None:
        api = _setup_api()

        with self.assertRaises(TypeError):
            api.setup_initial_world(_typical_run_baseline_combination())

        with self.assertRaises(ValueError):
            api.setup_initial_world(_typical_run_baseline_combination(), seed=None)

    def test_setup_uses_local_rng_without_mutating_global_random_state(self) -> None:
        api = _setup_api()

        random.seed(20260707)
        expected_global_draws = tuple(random.random() for _ in range(5))

        random.seed(20260707)
        _setup_initialization(api, seed=BASELINE_SEED)
        observed_global_draws = tuple(random.random() for _ in range(5))

        self.assertEqual(observed_global_draws, expected_global_draws)

    def test_different_seeds_can_change_stochastic_setup_results(self) -> None:
        api = _setup_api()

        first_world = _initialized_world(_setup_initialization(api, seed=BASELINE_SEED))
        second_world = _initialized_world(
            _setup_initialization(api, seed=DIFFERENT_SEED)
        )

        self.assertNotEqual(_world_snapshot(first_world), _world_snapshot(second_world))

    def test_household_income_and_informality_are_populated_from_setup(
        self,
    ) -> None:
        api = _setup_api()

        world = _initialized_world(_setup_initialization(api, seed=BASELINE_SEED))
        repeat_world = _initialized_world(
            _setup_initialization(api, seed=BASELINE_SEED)
        )
        different_seed_world = _initialized_world(
            _setup_initialization(api, seed=DIFFERENT_SEED)
        )
        repeat_households_by_coordinate = _households_by_coordinate(repeat_world)
        different_seed_households_by_coordinate = _households_by_coordinate(
            different_seed_world
        )
        informality_values = {household.informal for household in world.households}
        income_mismatch_coordinates = []
        non_bool_informality_coordinates = []

        self.assertEqual(informality_values, {False, True})

        for household in world.households:
            patch = world.patches[household.coordinate]
            repeat_household = repeat_households_by_coordinate[household.coordinate][0]

            if abs(household.income - (3.3 * patch.rent)) > 1e-9:
                income_mismatch_coordinates.append(household.coordinate)
            if type(household.informal) is not bool:
                non_bool_informality_coordinates.append(household.coordinate)

            self.assertEqual(household.informal, repeat_household.informal)

        self.assertEqual(income_mismatch_coordinates[:10], [])
        self.assertEqual(non_bool_informality_coordinates[:10], [])

        self.assertNotEqual(
            tuple(
                (household.coordinate, household.informal, household.income)
                for household in sorted(
                    world.households,
                    key=lambda item: item.coordinate,
                )
            ),
            tuple(
                (
                    household.coordinate,
                    household.informal,
                    household.income,
                )
                for household in sorted(
                    different_seed_world.households,
                    key=lambda item: item.coordinate,
                )
            ),
        )
        self.assertEqual(
            set(different_seed_households_by_coordinate),
            {household.coordinate for household in world.households},
        )

    def test_setup_household_classes_are_populated_and_seed_deterministic(
        self,
    ) -> None:
        api = _setup_api()

        world = _initialized_world(_setup_initialization(api, seed=BASELINE_SEED))
        repeat_world = _initialized_world(
            _setup_initialization(api, seed=BASELINE_SEED)
        )
        observed_classes = {household.income_class for household in world.households}

        self.assertLessEqual(observed_classes, SOURCE_INCOME_CLASS_VALUES)
        self.assertTrue(all(household.class_updated for household in world.households))
        self.assertEqual(
            tuple(
                (household.coordinate, household.income_class, household.class_updated)
                for household in sorted(
                    world.households,
                    key=lambda item: item.coordinate,
                )
            ),
            tuple(
                (household.coordinate, household.income_class, household.class_updated)
                for household in sorted(
                    repeat_world.households,
                    key=lambda item: item.coordinate,
                )
            ),
        )

    def test_setup_household_classes_match_sample_standard_deviation_thresholds(
        self,
    ) -> None:
        api = _setup_api()

        world = _initialized_world(_setup_initialization(api, seed=BASELINE_SEED))
        _, _, red_threshold, green_threshold = _source_income_class_thresholds(world)

        for household in world.households:
            with self.subTest(coordinate=household.coordinate):
                expected_class = _source_income_class_for(
                    household.income,
                    red_threshold,
                    green_threshold,
                )

                self.assertIsNotNone(expected_class)
                self.assertEqual(household.income_class, expected_class)
                self.assertTrue(household.class_updated)

    def test_baseline_setup_searching_is_false_when_source_rules_do_not_trigger(
        self,
    ) -> None:
        api = _setup_api()
        parameters = api.load_setup_parameters(_typical_run_baseline_combination())

        world = _initialized_world(_setup_initialization(api, seed=BASELINE_SEED))
        households_by_coordinate = _households_by_coordinate(world)

        for household in world.households:
            with self.subTest(coordinate=household.coordinate):
                patch = world.patches[household.coordinate]
                rent_search_threshold = (
                    (1 + parameters.staying_power) * 0.3 * household.income
                )
                mixed_class_patch = any(
                    other_household is not household
                    and other_household.income_class != household.income_class
                    for other_household in households_by_coordinate[
                        household.coordinate
                    ]
                )
                expected_searching = (
                    patch.rent_payable > rent_search_threshold or mixed_class_patch
                )

                self.assertFalse(expected_searching)
                self.assertFalse(household.searching)

    def test_setup_willingness_follows_source_rule_with_green_and_blue_forced_false(
        self,
    ) -> None:
        api = _setup_api()
        parameters = api.load_setup_parameters(_typical_run_baseline_combination())

        world = _initialized_world(_setup_initialization(api, seed=BASELINE_SEED))

        for household in world.households:
            with self.subTest(coordinate=household.coordinate):
                patch = world.patches[household.coordinate]
                rent_willingness_threshold = (
                    (1 - parameters.price_sensitivity) * 0.3 * household.income
                )
                source_rule_willing = patch.rent_payable > rent_willingness_threshold
                expected_willing = (
                    source_rule_willing and household.income_class == "red"
                )

                self.assertEqual(household.willing, expected_willing)
                if household.income_class in {"green", "blue"}:
                    self.assertFalse(household.willing)

    def test_patch_availability_matches_source_setup_logic_after_willingness(
        self,
    ) -> None:
        api = _setup_api()

        world = _initialized_world(_setup_initialization(api, seed=BASELINE_SEED))
        households_by_coordinate = _households_by_coordinate(world)
        red_willing_available_count = 0
        forced_unavailable_count = 0

        for coordinate, patch in world.patches.items():
            with self.subTest(coordinate=coordinate):
                patch_households = households_by_coordinate.get(coordinate, [])
                expected_available = (
                    True
                    if not patch_households
                    else not any(
                        not household.willing for household in patch_households
                    )
                )

                self.assertEqual(patch.available, expected_available)

                if not patch_households:
                    self.assertTrue(patch.available)
                    continue

                household = patch_households[0]
                if household.income_class == "red" and household.willing:
                    self.assertTrue(patch.available)
                    red_willing_available_count += 1
                if household.income_class in {"green", "blue"}:
                    self.assertFalse(household.willing)
                    self.assertFalse(patch.available)
                    forced_unavailable_count += 1

        self.assertGreater(red_willing_available_count, 0)
        self.assertGreater(forced_unavailable_count, 0)

    def test_setup_resicat_matches_household_class_for_occupied_non_slum_patches(
        self,
    ) -> None:
        api = _setup_api()
        initial_city_limit = _typical_run_baseline_parameters()["initialcitylimit"]
        inclusive_city_core = _inclusive_city_core_coordinates(initial_city_limit)

        world = _initialized_world(_setup_initialization(api, seed=BASELINE_SEED))
        households_by_coordinate = _households_by_coordinate(world)

        for coordinate, patch in world.patches.items():
            with self.subTest(coordinate=coordinate):
                if coordinate not in inclusive_city_core:
                    self.assertEqual(patch.resicat, 0)
                    continue

                self.assertFalse(patch.slum)
                self.assertEqual(len(households_by_coordinate[coordinate]), 1)
                household = households_by_coordinate[coordinate][0]
                self.assertEqual(
                    patch.resicat,
                    SOURCE_RESICAT_BY_CLASS[household.income_class],
                )

    def test_resicat_post_processing_preserves_source_independent_if_order(
        self,
    ) -> None:
        api = _setup_api()
        world = slumulation.build_empty_world()
        coordinate = (0, 0)
        world.households = [
            slumulation.HouseholdState(x=0, y=0, income_class="red"),
            slumulation.HouseholdState(x=0, y=0, income_class="blue"),
            slumulation.HouseholdState(x=0, y=0, income_class="green"),
        ]
        patch = world.patches[coordinate]
        patch.num_units = 1
        patch.slum = False

        households_by_coordinate = api.module._households_by_coordinate(world)
        api.module._update_initial_patch_occupancy(world, households_by_coordinate)
        api.module._update_initial_patch_residential_categories(
            world,
            households_by_coordinate,
        )

        self.assertGreater(patch.num_occupants, patch.num_units)
        self.assertEqual(patch.resicat, 1)

    def test_baseline_setup_has_no_slums_with_one_household_per_unit(
        self,
    ) -> None:
        api = _setup_api()

        world = _initialized_world(_setup_initialization(api, seed=BASELINE_SEED))

        for coordinate, patch in world.patches.items():
            with self.subTest(coordinate=coordinate):
                self.assertFalse(patch.slum)
                self.assertEqual(patch.slum_occupants, 0)
                if patch.occupied:
                    self.assertEqual(patch.num_occupants, 1)
                    self.assertEqual(patch.num_units, 1)

    def test_baseline_setup_creates_no_developers(self) -> None:
        api = _setup_api()

        initialization = _setup_initialization(api, seed=BASELINE_SEED)
        world = _initialized_world(initialization)

        self.assertEqual(world.developers, [])
        self.assertEqual(initialization.developers, [])

    def test_setup_finalizes_time_city_income_population_and_counts(self) -> None:
        api = _setup_api()

        initialization = _setup_initialization(api, seed=BASELINE_SEED)
        world = _initialized_world(initialization)
        class_counts = Counter(household.income_class for household in world.households)

        self.assertEqual(_summary_value(initialization, "time"), 0)
        self.assertAlmostEqual(
            _summary_value(initialization, "cityincome", "city_income"),
            sum(household.income for household in world.households),
        )
        self.assertEqual(
            _summary_value(initialization, "population"),
            len(world.households),
        )
        self.assertEqual(
            _summary_value(initialization, "red_count"), class_counts["red"]
        )
        self.assertEqual(
            _summary_value(initialization, "blue_count"),
            class_counts["blue"],
        )
        self.assertEqual(
            _summary_value(initialization, "green_count"),
            class_counts["green"],
        )
        self.assertEqual(
            _summary_value(initialization, "num_searching", "num-searching"),
            sum(household.searching for household in world.households),
        )
        self.assertEqual(
            _summary_value(
                initialization,
                "num_developers",
                "num-developers",
                "developer_count",
            ),
            0,
        )

    def test_setup_rent_density_and_class_averages_match_world_state(self) -> None:
        api = _setup_api()

        initialization = _setup_initialization(api, seed=BASELINE_SEED)
        world = _initialized_world(initialization)
        patch_rents = [patch.rent for patch in world.patches.values()]
        occupied_patch_count = sum(patch.occupied for patch in world.patches.values())
        class_counts = Counter(household.income_class for household in world.households)
        resicat_counts = Counter(patch.resicat for patch in world.patches.values())

        self.assertEqual(
            _summary_value(initialization, "highestrent", "highest_rent"),
            max(patch_rents),
        )
        self.assertEqual(
            _summary_value(initialization, "lowestrent", "lowest_rent"),
            min(patch_rents),
        )
        self.assertAlmostEqual(
            _summary_value(initialization, "avg_density", "avg-density"),
            len(world.households) / occupied_patch_count,
        )

        for income_class, resicat in SOURCE_RESICAT_BY_CLASS.items():
            with self.subTest(income_class=income_class):
                class_households = [
                    household
                    for household in world.households
                    if household.income_class == income_class
                ]
                expected_density = class_counts[income_class] / resicat_counts[resicat]

                self.assertGreater(len(class_households), 0)
                self.assertAlmostEqual(
                    _summary_value(
                        initialization,
                        f"{income_class}_density",
                        f"{income_class}-density",
                    ),
                    expected_density,
                )
                self.assertAlmostEqual(
                    _summary_value(
                        initialization,
                        f"avg_income_{income_class}",
                        f"{income_class}_average_income",
                    ),
                    _mean([household.income for household in class_households]),
                )
                self.assertAlmostEqual(
                    _summary_value(
                        initialization,
                        f"{income_class}_averagerent",
                        f"{income_class}_average_rent",
                    ),
                    _mean(_household_patch_rent_payables(world, income_class)),
                )

        self.assertAlmostEqual(
            _summary_value(initialization, "avg_income", "average_income"),
            _summary_value(initialization, "cityincome", "city_income")
            / len(world.households),
        )

    def test_setup_baseline_slum_metrics_are_zero(self) -> None:
        api = _setup_api()

        initialization = _setup_initialization(api, seed=BASELINE_SEED)

        for aliases in (
            ("slumpop", "slum_pop"),
            ("central_slumpop", "central_slum_pop"),
            ("peripheral_slumpop", "peripheral_slum_pop", "periphery_slum_pop"),
            ("slum_pop_percent",),
            ("num_slums",),
            ("central_num_slums",),
            ("peripheral_num_slums",),
            ("slum_area_percent",),
            ("central_slum_area_percent",),
            ("periphery_slum_area_percent",),
            ("slum_density",),
            ("central_slum_density",),
            ("periphery_slum_density",),
            ("smallest_slum",),
        ):
            with self.subTest(metric=aliases[0]):
                self.assertEqual(_summary_value(initialization, *aliases), 0)

        largest_slum = _maybe_summary_value(
            initialization,
            "largest_slum",
            "largest-slum",
        )
        if largest_slum is not _MISSING:
            self.assertEqual(largest_slum, 0)

    def test_setup_ward_population_summaries_match_patch_state(self) -> None:
        api = _setup_api()

        initialization = _setup_initialization(api, seed=BASELINE_SEED)
        world = _initialized_world(initialization)
        expected_ward_populations = _expected_ward_patch_sums(world, "num_occupants")
        expected_ward_slum_populations = _expected_ward_patch_sums(
            world,
            "slum_occupants",
        )
        expected_ward_slum_shares = {
            ward: (
                expected_ward_slum_populations[ward] / expected_ward_populations[ward]
                if expected_ward_populations[ward] > 0
                else 0
            )
            for ward in range(1, 10)
        }

        ward_populations = _ward_summary_values(
            initialization,
            "ward_populations",
            "ward_population",
            "wardpop",
            stem="pop",
        )
        ward_slum_populations = _ward_summary_values(
            initialization,
            "ward_slum_populations",
            "ward_slum_population",
            "ward_slumpop",
            stem="slumpop",
        )
        ward_slum_shares = _ward_summary_values(
            initialization,
            "ward_slum_pop_percents",
            "ward_slum_pop_percent",
            "ward_slumpoppercent",
            stem="slumpoppercent",
        )

        self.assertEqual(sum(ward_populations.values()), len(world.households))
        self.assertEqual(ward_populations, expected_ward_populations)
        self.assertEqual(ward_slum_populations, expected_ward_slum_populations)

        for ward in range(1, 10):
            with self.subTest(ward=ward):
                self.assertEqual(ward_slum_populations[ward], 0)
                self.assertEqual(
                    ward_slum_shares[ward], expected_ward_slum_shares[ward]
                )

        self.assertEqual(
            _summary_value(
                initialization,
                "central_slum_pop_percent",
                "centralslumpoppercent",
            ),
            expected_ward_slum_shares[5] * 100,
        )
        self.assertEqual(
            _summary_value(
                initialization,
                "periphery_slum_pop_percent",
                "peripheryslumpoppercent",
            ),
            0,
        )

    def test_setup_slice_does_not_publish_simulation_or_output_apis(self) -> None:
        api = _setup_api()
        world = _initialized_world(_setup_initialization(api))
        namespaces = (
            ("slumulation", slumulation),
            ("slumulation.setup", api.module),
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
