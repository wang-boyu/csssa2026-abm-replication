from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import product
import unittest

from slumulation import constants

EXPECTED_SELECTED_EXPERIMENTS = (
    "Typical Run",
    "Population Growth Rate",
    "Politics and Development ON OFF",
)

EXPECTED_EXCLUDED_EXPERIMENTS = {
    "Urbanization",
    "EconomicGrowth",
    "PrimeLand",
    "No Center Search (Old)",
    "Central Search Off",
}

EXPECTED_PARAMETER_CROSSWALK = {
    "staying-power": "staying_power",
    "percent-inappropriate-land": "percent_inappropriate_land",
    "informalityindex": "informality_index",
    "percent-prime-land": "percent_prime_land",
    "initialcitylimit": "initial_city_limit",
    "popgrowthrate": "population_growth_rate",
    "SimulationRuntime": "simulation_runtime",
    "Politics": "politics",
    "Develop": "develop",
    "price-sensitivity": "price_sensitivity",
    "diffusion-rate": "diffusion_rate",
    "economicgrowthrate": "economic_growth_rate",
    "initialinequality": "initial_inequality",
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

EXPECTED_PRIMARY_METRICS = (
    "slumpoppercent",
    "centralslumpoppercent",
    "peripheryslumpoppercent",
    "num-slums",
    "central-num-slums",
    "peripheral-num-slums",
    "slumareapercent",
    "centralslumareapercent",
    "peripheryslumareapercent",
    "slum-density",
    "central-slum-density",
    "periphery-slum-density",
)

EXPECTED_SOURCE_EMITTED_METRICS = EXPECTED_PRIMARY_METRICS + (
    "red-density",
    "blue-density",
    "green-density",
    "smallest-slum",
    "largest-slum",
)

EXPECTED_WARD_BOUNDS = {
    1: (-25, -9, -25, -9),
    2: (-8, 8, -25, -9),
    3: (9, 25, -25, -9),
    4: (-25, -9, -8, 8),
    5: (-8, 8, -8, 8),
    6: (9, 25, -8, 8),
    7: (-25, -9, 9, 25),
    8: (-8, 8, 9, 25),
    9: (9, 25, 9, 25),
}


def _field(record, *names):
    if isinstance(record, Mapping):
        for name in names:
            if name in record:
                return record[name]

    for name in names:
        if hasattr(record, name):
            return getattr(record, name)

    raise AssertionError(f"Missing expected field from {record!r}: {names!r}")


def _optional_field(record, *names):
    try:
        return _field(record, *names)
    except AssertionError:
        return None


def _registry_by_name(registry):
    if isinstance(registry, Mapping):
        records = {}
        for name, record in registry.items():
            experiment_name = (
                name
                if isinstance(name, str)
                else _field(record, "name", "experiment_name")
            )
            records[experiment_name] = record
        return records

    return {_field(record, "name", "experiment_name"): record for record in registry}


def _parameter_combinations(experiment):
    combinations = _field(
        experiment,
        "parameter_combinations",
        "combinations",
        "parameter_grid",
    )

    if isinstance(combinations, Mapping):
        if any(_is_non_string_sequence(value) for value in combinations.values()):
            keys = tuple(combinations)
            value_options = tuple(
                value if _is_non_string_sequence(value) else (value,)
                for value in combinations.values()
            )
            return tuple(
                dict(zip(keys, values, strict=True))
                for values in product(*value_options)
            )

        return (combinations,)

    return tuple(combinations)


def _is_non_string_sequence(value):
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _parameters_for_combination(combination):
    if isinstance(combination, Mapping):
        for key in ("parameters", "netlogo_parameters", "parameter_values"):
            if key in combination:
                return combination[key]
        return combination

    return _field(combination, "parameters", "netlogo_parameters", "parameter_values")


def _normalized_bool(value):
    if isinstance(value, str):
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
    return value


def _crosswalk_aliases(crosswalk):
    aliases = {}

    if isinstance(crosswalk, Mapping):
        for key, value in crosswalk.items():
            if isinstance(key, str) and key in EXPECTED_PARAMETER_CROSSWALK:
                netlogo_name = key
                mesa_alias = (
                    value
                    if isinstance(value, str)
                    else _field(
                        value,
                        "mesa_alias",
                        "alias",
                        "python_name",
                        "mesa_name",
                    )
                )
            else:
                netlogo_name = _field(
                    value,
                    "netlogo_name",
                    "source_name",
                    "netlogo_parameter",
                    "name",
                )
                mesa_alias = _field(
                    value,
                    "mesa_alias",
                    "alias",
                    "python_name",
                    "mesa_name",
                )

            aliases[netlogo_name] = mesa_alias

        return aliases

    for item in crosswalk:
        if isinstance(item, tuple) and len(item) >= 2:
            netlogo_name, mesa_alias = item[:2]
        else:
            netlogo_name = _field(
                item,
                "netlogo_name",
                "source_name",
                "netlogo_parameter",
                "name",
            )
            mesa_alias = _field(
                item,
                "mesa_alias",
                "alias",
                "python_name",
                "mesa_name",
            )
        aliases[netlogo_name] = mesa_alias

    return aliases


def _surface_step_range(surface):
    explicit_range = _optional_field(surface, "step_range", "steps")
    if explicit_range is not None:
        return tuple(explicit_range)

    return (
        _field(surface, "step_min", "min_step"),
        _field(surface, "step_max", "max_step"),
    )


def _bounds_tuple(bounds):
    if _is_non_string_sequence(bounds):
        return tuple(bounds)

    return (
        _field(bounds, "x_min", "min_x", "min_pxcor"),
        _field(bounds, "x_max", "max_x", "max_pxcor"),
        _field(bounds, "y_min", "min_y", "min_pycor"),
        _field(bounds, "y_max", "max_y", "max_pycor"),
    )


def _ward_bounds_by_id(ward_bounds):
    if isinstance(ward_bounds, Mapping):
        return {
            int(ward_id): _bounds_tuple(bounds)
            for ward_id, bounds in ward_bounds.items()
        }

    return {
        int(_field(bounds, "ward", "id", "ward_id")): _bounds_tuple(bounds)
        for bounds in ward_bounds
    }


class SlumulationConstantsTests(unittest.TestCase):
    def test_selected_experiment_names_are_exact_bounded_surface(self) -> None:
        self.assertEqual(
            tuple(constants.SELECTED_EXPERIMENT_NAMES),
            EXPECTED_SELECTED_EXPERIMENTS,
        )

        registry = _registry_by_name(constants.EXPERIMENT_REGISTRY)
        self.assertEqual(set(registry), set(EXPECTED_SELECTED_EXPERIMENTS))

    def test_registry_excludes_stale_behaviorspace_experiments(self) -> None:
        registry = _registry_by_name(constants.EXPERIMENT_REGISTRY)

        self.assertFalse(set(registry) & EXPECTED_EXCLUDED_EXPERIMENTS)
        self.assertNotIn("informal-formal-economy", registry)

    def test_registry_parameter_grids_match_selected_reference_surface(self) -> None:
        registry = _registry_by_name(constants.EXPERIMENT_REGISTRY)

        typical_combinations = _parameter_combinations(registry["Typical Run"])
        population_combinations = _parameter_combinations(
            registry["Population Growth Rate"]
        )
        politics_combinations = _parameter_combinations(
            registry["Politics and Development ON OFF"]
        )

        self.assertEqual(len(typical_combinations), 1)
        self.assertEqual(len(population_combinations), 3)
        self.assertEqual(len(politics_combinations), 4)

        self.assertEqual(
            _parameters_for_combination(typical_combinations[0]),
            EXPECTED_BASELINE_PARAMETERS,
        )

        for combination in population_combinations + politics_combinations:
            self.assertNotIn(
                "informal-formal-economy",
                _parameters_for_combination(combination),
            )

        self.assertEqual(
            {
                _parameters_for_combination(combination)["popgrowthrate"]
                for combination in population_combinations
            },
            {2, 3, 4},
        )
        self.assertEqual(
            {
                (
                    _normalized_bool(
                        _parameters_for_combination(combination)["Politics"]
                    ),
                    _normalized_bool(
                        _parameters_for_combination(combination)["Develop"]
                    ),
                )
                for combination in politics_combinations
            },
            {(True, True), (True, False), (False, True), (False, False)},
        )

    def test_parameter_crosswalk_has_selected_names_and_aliases(self) -> None:
        aliases = _crosswalk_aliases(constants.PARAMETER_CROSSWALK)

        self.assertEqual(aliases, EXPECTED_PARAMETER_CROSSWALK)
        self.assertNotIn("informal-formal-economy", aliases)

    def test_metric_constants_keep_largest_slum_raw_only(self) -> None:
        source_metrics = tuple(constants.SOURCE_EMITTED_METRICS)
        primary_metrics = tuple(constants.PRIMARY_VALIDATION_METRICS)

        self.assertEqual(set(source_metrics), set(EXPECTED_SOURCE_EMITTED_METRICS))
        self.assertEqual(set(primary_metrics), set(EXPECTED_PRIMARY_METRICS))
        self.assertIn("largest-slum", source_metrics)
        self.assertNotIn("largest-slum", primary_metrics)
        self.assertTrue(set(primary_metrics).issubset(source_metrics))

    def test_reference_surface_30_rep_totals_are_documented(self) -> None:
        surface = constants.REFERENCE_SURFACE_30_REP

        self.assertEqual(
            _field(
                surface,
                "parameter_combinations",
                "parameter_combination_count",
                "total_parameter_combinations",
            ),
            8,
        )
        self.assertEqual(
            _field(surface, "runs", "total_runs"),
            240,
        )
        self.assertEqual(
            _field(surface, "data_rows", "total_data_rows", "rows"),
            12_240,
        )
        self.assertEqual(_surface_step_range(surface), (0, 50))
        self.assertEqual(
            _field(surface, "rows_per_run", "step_rows_per_run"),
            51,
        )

    def test_world_bounds_and_ward_constants_match_netlogo_surface(self) -> None:
        self.assertEqual(_bounds_tuple(constants.WORLD_BOUNDS), (-25, 25, -25, 25))
        self.assertEqual(constants.CENTRAL_WARD, 5)
        self.assertEqual(
            set(constants.PERIPHERAL_WARDS),
            {1, 2, 3, 4, 6, 7, 8, 9},
        )
        self.assertEqual(
            _ward_bounds_by_id(constants.WARD_BOUNDS),
            EXPECTED_WARD_BOUNDS,
        )


if __name__ == "__main__":
    unittest.main()
