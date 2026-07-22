from __future__ import annotations

import csv
import importlib
import inspect
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import slumulation
from slumulation import constants
from slumulation.dynamics import SlumulateStepResult
from slumulation.state import build_empty_world

EXPECTED_BEHAVIORSPACE_COLUMNS = (
    ("[run number]",)
    + constants.PARAMETER_FIELD_ORDER
    + ("[step]",)
    + constants.SOURCE_EMITTED_METRICS
)
EXPECTED_SELECTED_EXPERIMENTS = (
    "Typical Run",
    "Population Growth Rate",
    "Politics and Development ON OFF",
)
EXCLUDED_EXPERIMENT_NAMES = ("Urbanization", "EconomicGrowth")


def _runner_api() -> SimpleNamespace:
    runner = importlib.import_module("slumulation.runner")
    expected_exports = (
        "behavior_space_columns",
        "metric_values",
        "build_behavior_space_row",
        "selected_experiment_specs",
        "run_behavior_space_rows",
        "write_behavior_space_rows",
    )
    missing = [name for name in expected_exports if not hasattr(runner, name)]

    if missing:
        raise AssertionError(
            f"slumulation.runner is missing expected public exports: {missing!r}"
        )

    return SimpleNamespace(
        module=runner,
        **{name: getattr(runner, name) for name in expected_exports},
    )


def _call_with_supported_keywords(function, **kwargs):
    signature = inspect.signature(function)

    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return function(**kwargs)

    supported_kwargs = {
        name: value for name, value in kwargs.items() if name in signature.parameters
    }
    return function(**supported_kwargs)


def _baseline_parameters() -> dict[str, object]:
    return dict(constants.BASELINE_PARAMETER_VALUES)


def _parameters_for_combination(combination) -> dict[str, object]:
    if isinstance(combination, dict):
        values = combination.get("parameter_values", combination.get("parameters"))
        return dict(values if values is not None else combination)

    for name in ("parameter_values", "parameters"):
        if hasattr(combination, name):
            return dict(getattr(combination, name))

    return dict(combination)


def _experiment_names(specs) -> tuple[str, ...]:
    return tuple(
        spec["name"] if isinstance(spec, dict) else spec.name for spec in specs
    )


def _metric_summary(**overrides) -> SimpleNamespace:
    values = {
        entry.mesa_alias: index + 0.25
        for index, entry in enumerate(constants.METRIC_CROSSWALK, start=1)
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _world(**summary_overrides) -> SimpleNamespace:
    world = build_empty_world()
    world.summary = _metric_summary(**summary_overrides)
    return world


def _as_parameter_dict(parameter_values) -> dict[str, object]:
    if hasattr(parameter_values, "parameter_values"):
        return dict(parameter_values.parameter_values)
    if hasattr(parameter_values, "parameters"):
        return dict(parameter_values.parameters)
    return dict(parameter_values)


def _row_mapping(row) -> dict[str, object]:
    columns = tuple(EXPECTED_BEHAVIORSPACE_COLUMNS)

    if isinstance(row, dict):
        return dict(row)

    return dict(zip(columns, row, strict=True))


def _row_columns(row) -> tuple[str, ...]:
    if isinstance(row, dict):
        return tuple(row)

    return tuple(EXPECTED_BEHAVIORSPACE_COLUMNS)


def _build_row(api, *, run_number=7, step=0, parameters=None, world=None):
    if parameters is None:
        parameters = _baseline_parameters()
    if world is None:
        world = _world()

    return _call_with_supported_keywords(
        api.build_behavior_space_row,
        run=run_number,
        run_number=run_number,
        parameter_values=parameters,
        parameters=parameters,
        step=step,
        world=world,
    )


def _csv_row(prefix: str) -> dict[str, str]:
    return {
        column: f"{prefix}-{index:02d}"
        for index, column in enumerate(EXPECTED_BEHAVIORSPACE_COLUMNS)
    }


def _reverse_ordered_csv_row(prefix: str) -> dict[str, str]:
    values = _csv_row(prefix)
    return {
        column: values[column] for column in reversed(EXPECTED_BEHAVIORSPACE_COLUMNS)
    }


def _read_csv(path: Path) -> list[list[str]]:
    with path.open(newline="") as file:
        return list(csv.reader(file))


class SlumulationRunnerTests(unittest.TestCase):
    def test_runner_exports_stay_on_runner_module_not_package_root(self) -> None:
        api = _runner_api()
        expected_exports = {
            "behavior_space_columns",
            "metric_values",
            "build_behavior_space_row",
            "selected_experiment_specs",
            "run_behavior_space_rows",
            "write_behavior_space_rows",
        }

        self.assertTrue(expected_exports.issubset(set(api.module.__all__)))

        package_exports = set(getattr(slumulation, "__all__", ()))
        for name in expected_exports:
            with self.subTest(name=name):
                self.assertNotIn(name, package_exports)

    def test_behavior_space_columns_match_reference_order_and_count(self) -> None:
        api = _runner_api()

        columns = tuple(api.behavior_space_columns())

        self.assertEqual(columns, EXPECTED_BEHAVIORSPACE_COLUMNS)
        self.assertEqual(len(columns), 32)

    def test_selected_experiment_specs_are_bounded_to_initial_surface(self) -> None:
        api = _runner_api()

        selected_specs = api.selected_experiment_specs()

        self.assertEqual(
            _experiment_names(selected_specs), EXPECTED_SELECTED_EXPERIMENTS
        )

        for excluded_name in EXCLUDED_EXPERIMENT_NAMES:
            with self.subTest(excluded_name=excluded_name):
                with self.assertRaises(ValueError):
                    api.selected_experiment_specs((excluded_name,))

    def test_build_behavior_space_row_preserves_column_order_and_raw_metrics(
        self,
    ) -> None:
        api = _runner_api()
        parameters = {
            **_baseline_parameters(),
            "popgrowthrate": 4,
            "Politics": False,
            "Develop": True,
        }

        row = _build_row(api, run_number=11, step=0, parameters=parameters)
        row_by_column = _row_mapping(row)

        self.assertEqual(_row_columns(row), EXPECTED_BEHAVIORSPACE_COLUMNS)
        self.assertEqual(len(row_by_column), 32)
        self.assertEqual(row_by_column["[run number]"], 11)
        self.assertEqual(row_by_column["[step]"], 0)

        for parameter_name in constants.PARAMETER_FIELD_ORDER:
            with self.subTest(parameter_name=parameter_name):
                self.assertIn(parameter_name, row_by_column)
                self.assertEqual(
                    row_by_column[parameter_name], parameters[parameter_name]
                )

        for metric_name in constants.SOURCE_EMITTED_METRICS:
            with self.subTest(metric_name=metric_name):
                self.assertIn(metric_name, row_by_column)

    def test_metric_values_include_largest_slum_raw_only(self) -> None:
        api = _runner_api()

        metrics = api.metric_values(_world())

        self.assertEqual(tuple(metrics), constants.SOURCE_EMITTED_METRICS)
        self.assertIn("largest-slum", metrics)
        self.assertIn("largest-slum", constants.SOURCE_EMITTED_METRICS)
        self.assertNotIn("largest-slum", constants.PRIMARY_VALIDATION_METRICS)

    def test_run_behavior_space_rows_emits_setup_and_tick_advanced_yearly_rows(
        self,
    ) -> None:
        api = _runner_api()
        call_log: list[tuple[str, int, object]] = []

        def setup_fn(parameter_values, seed):
            world = _world()
            parameters = _as_parameter_dict(parameter_values)
            call_log.append(("setup", world.time, parameters["popgrowthrate"]))
            return SimpleNamespace(world=world, parameters=parameters, seed=seed)

        def step_fn(world, parameters, rng):
            parameter_values = _as_parameter_dict(parameters)
            call_log.append(("step", world.time, parameter_values["popgrowthrate"]))
            if len([entry for entry in call_log if entry[0] == "step"]) <= 2:
                world.time += 1
                return SlumulateStepResult(stopped=False, tick_advanced=True)

            world.time = 51
            return SlumulateStepResult(stopped=True, tick_advanced=False)

        typical_run = api.selected_experiment_specs(("Typical Run",))[0]
        rows = list(
            api.run_behavior_space_rows(
                typical_run,
                setup_fn=setup_fn,
                step_fn=step_fn,
                seed=1234,
                max_steps=3,
            )
        )

        row_steps = [_row_mapping(row)["[step]"] for row in rows]

        self.assertEqual(row_steps, [0, 1, 2])
        self.assertNotIn(51, row_steps)
        self.assertEqual(
            [entry[0] for entry in call_log],
            ["setup", "step", "step", "step"],
        )

    def test_run_behavior_space_rows_calls_injected_step_function(self) -> None:
        api = _runner_api()
        calls: list[str] = []

        def setup_fn(parameter_values, seed):
            calls.append("setup")
            return SimpleNamespace(
                world=_world(),
                parameters=_as_parameter_dict(parameter_values),
                seed=seed,
            )

        def step_fn(world, parameters, rng):
            calls.append("injected-step")
            return SlumulateStepResult(stopped=True, tick_advanced=False)

        typical_run = api.selected_experiment_specs(("Typical Run",))[0]
        rows = list(
            api.run_behavior_space_rows(
                typical_run,
                setup_fn=setup_fn,
                step_fn=step_fn,
                seed=2026,
                max_steps=1,
            )
        )

        self.assertEqual([_row_mapping(row)["[step]"] for row in rows], [0])
        self.assertEqual(calls, ["setup", "injected-step"])

    def test_selected_specs_preserve_reference_parameter_combinations(self) -> None:
        api = _runner_api()

        specs_by_name = {
            name: spec
            for name, spec in zip(
                _experiment_names(api.selected_experiment_specs()),
                api.selected_experiment_specs(),
                strict=True,
            )
        }

        typical_parameters = [
            _parameters_for_combination(combination)
            for combination in specs_by_name["Typical Run"].parameter_combinations
        ]
        population_rates = {
            _parameters_for_combination(combination)["popgrowthrate"]
            for combination in specs_by_name[
                "Population Growth Rate"
            ].parameter_combinations
        }
        politics_develop_values = {
            (
                _parameters_for_combination(combination)["Politics"],
                _parameters_for_combination(combination)["Develop"],
            )
            for combination in specs_by_name[
                "Politics and Development ON OFF"
            ].parameter_combinations
        }

        self.assertEqual(typical_parameters, [_baseline_parameters()])
        self.assertEqual(population_rates, {2, 3, 4})
        self.assertEqual(
            politics_develop_values,
            {(True, True), (True, False), (False, True), (False, False)},
        )

    def test_write_behavior_space_rows_creates_csv_with_reference_header(self) -> None:
        api = _runner_api()
        row = _reverse_ordered_csv_row("row")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bounded-output.csv"

            api.write_behavior_space_rows(path, [row])

            self.assertTrue(path.is_file())
            csv_rows = _read_csv(path)

        self.assertEqual(csv_rows[0], list(api.behavior_space_columns()))
        self.assertEqual(len(csv_rows[0]), 32)

    def test_write_behavior_space_rows_writes_values_in_column_order(self) -> None:
        api = _runner_api()
        row = _reverse_ordered_csv_row("ordered")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ordered-output.csv"

            api.write_behavior_space_rows(path, [row])

            csv_rows = _read_csv(path)

        self.assertEqual(
            csv_rows,
            [
                list(EXPECTED_BEHAVIORSPACE_COLUMNS),
                [row[column] for column in EXPECTED_BEHAVIORSPACE_COLUMNS],
            ],
        )

    def test_write_behavior_space_rows_preserves_multiple_row_order(self) -> None:
        api = _runner_api()
        first_row = _reverse_ordered_csv_row("first")
        second_row = _reverse_ordered_csv_row("second")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multi-row-output.csv"

            api.write_behavior_space_rows(path, [first_row, second_row])

            csv_rows = _read_csv(path)

        self.assertEqual(
            csv_rows,
            [
                list(EXPECTED_BEHAVIORSPACE_COLUMNS),
                [first_row[column] for column in EXPECTED_BEHAVIORSPACE_COLUMNS],
                [second_row[column] for column in EXPECTED_BEHAVIORSPACE_COLUMNS],
            ],
        )

    def test_write_behavior_space_rows_empty_rows_produce_header_only_csv(
        self,
    ) -> None:
        api = _runner_api()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "header-only-output.csv"

            api.write_behavior_space_rows(path, [])

            csv_rows = _read_csv(path)

        self.assertEqual(csv_rows, [list(EXPECTED_BEHAVIORSPACE_COLUMNS)])

    def test_write_behavior_space_rows_omits_netlogo_metadata_and_comments(
        self,
    ) -> None:
        api = _runner_api()
        row = _reverse_ordered_csv_row("plain")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plain-output.csv"

            api.write_behavior_space_rows(path, [row])

            raw_lines = path.read_text().splitlines()
            csv_rows = _read_csv(path)

        self.assertEqual(len(raw_lines), 2)
        self.assertEqual(csv_rows[0], list(EXPECTED_BEHAVIORSPACE_COLUMNS))
        self.assertNotIn("NetLogo", "\n".join(raw_lines))
        self.assertNotIn("BehaviorSpace", "\n".join(raw_lines))
        self.assertFalse(any(line.startswith("#") for line in raw_lines))

    def test_write_behavior_space_rows_does_not_run_simulation_or_validation(
        self,
    ) -> None:
        api = _runner_api()
        row = _reverse_ordered_csv_row("bounded")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bounded-output.csv"

            with (
                mock.patch.object(
                    api.module,
                    "run_behavior_space_rows",
                    side_effect=AssertionError("writer must not generate rows"),
                ),
                mock.patch.object(
                    api.module,
                    "setup_initial_world",
                    side_effect=AssertionError("writer must not run setup"),
                ),
                mock.patch.object(
                    api.module,
                    "slumulate_step",
                    side_effect=AssertionError("writer must not step the model"),
                ),
            ):
                api.write_behavior_space_rows(path, [row])

            csv_rows = _read_csv(path)

        self.assertEqual(
            csv_rows,
            [
                list(EXPECTED_BEHAVIORSPACE_COLUMNS),
                [row[column] for column in EXPECTED_BEHAVIORSPACE_COLUMNS],
            ],
        )


if __name__ == "__main__":
    unittest.main()
