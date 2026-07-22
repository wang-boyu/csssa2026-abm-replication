from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable, Mapping, Sequence
from os import PathLike
from pathlib import Path
from random import Random
from typing import TypeAlias

from .constants import (
    BEHAVIORSPACE_OUTPUT_COLUMNS,
    METRIC_CROSSWALK_BY_NETLOGO_NAME,
    PARAMETER_FIELD_ORDER,
    RAW_OUTPUT_COLUMNS,
    REFERENCE_REPETITIONS,
    SELECTED_EXPERIMENT_REGISTRY,
    SOURCE_EMITTED_METRIC_NAMES,
    ExperimentSpec,
    ParameterCombination,
)
from .dynamics import slumulate_step
from .setup import (
    SetupInitialization,
    SetupParameters,
    load_setup_parameters,
    setup_initial_world,
)
from .state import WorldState

BehaviorSpaceRow: TypeAlias = dict[str, object]


def behavior_space_columns() -> tuple[str, ...]:
    """Return the source-compatible BehaviorSpace data columns."""

    return BEHAVIORSPACE_OUTPUT_COLUMNS


def write_behavior_space_rows(
    path: str | PathLike[str],
    rows: Iterable[BehaviorSpaceRow],
) -> None:
    """Write BehaviorSpace-compatible data rows to a simple CSV file."""

    columns = behavior_space_columns()
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row[column] for column in columns])


def metric_values(world: WorldState) -> dict[str, int | float]:
    """Return source-emitted metrics keyed by NetLogo metric name."""

    values: dict[str, int | float] = {}
    for metric_name in SOURCE_EMITTED_METRIC_NAMES:
        crosswalk = METRIC_CROSSWALK_BY_NETLOGO_NAME[metric_name]
        value = getattr(world.summary, crosswalk.mesa_alias)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(
                f"Metric {metric_name!r} resolved to non-numeric value {value!r}."
            )
        values[metric_name] = value
    return values


def build_behavior_space_row(
    *,
    run_number: int,
    parameters: SetupParameters | Mapping[str, object] | object,
    step: int,
    world: WorldState,
) -> BehaviorSpaceRow:
    """Build one ordered raw-compatible BehaviorSpace data row."""

    setup_parameters = load_setup_parameters(parameters)
    parameter_values = setup_parameters.parameters
    metrics = metric_values(world)

    row: BehaviorSpaceRow = {"[run number]": run_number}
    for parameter_name in PARAMETER_FIELD_ORDER:
        row[parameter_name] = parameter_values[parameter_name]
    row["[step]"] = step
    for metric_name in SOURCE_EMITTED_METRIC_NAMES:
        row[metric_name] = metrics[metric_name]

    if tuple(row) != BEHAVIORSPACE_OUTPUT_COLUMNS:
        raise RuntimeError("BehaviorSpace row column order drifted from constants.")
    if len(row) != RAW_OUTPUT_COLUMNS:
        raise RuntimeError(
            f"BehaviorSpace row has {len(row)} columns; expected {RAW_OUTPUT_COLUMNS}."
        )
    return row


def selected_experiment_specs(
    experiment_names: Iterable[str] | None = None,
) -> tuple[ExperimentSpec, ...]:
    """Return selected validation experiment specs, rejecting unknown names."""

    if experiment_names is None:
        return tuple(SELECTED_EXPERIMENT_REGISTRY.values())

    specs: list[ExperimentSpec] = []
    for experiment_name in experiment_names:
        try:
            specs.append(SELECTED_EXPERIMENT_REGISTRY[experiment_name])
        except KeyError as exc:
            raise ValueError(
                f"Unknown or excluded Slumulation experiment: {experiment_name!r}."
            ) from exc
    return tuple(specs)


def run_behavior_space_rows(
    experiment: str | ExperimentSpec,
    *,
    parameter_combination: ParameterCombination | Mapping[str, object] | None = None,
    run_number: int = 1,
    seed: int | str,
    max_steps: int | None = None,
    setup_fn=setup_initial_world,
    step_fn=slumulate_step,
) -> tuple[BehaviorSpaceRow, ...]:
    """Run one in-memory BehaviorSpace-compatible row stream."""

    experiment_spec = _selected_experiment_spec(experiment)
    parameter_source = _parameter_source(experiment_spec, parameter_combination)
    setup_parameters = load_setup_parameters(parameter_source)
    setup_result = setup_fn(parameter_values=setup_parameters, seed=seed)
    world, setup_parameters = _world_and_parameters(setup_result, setup_parameters)

    rows: list[BehaviorSpaceRow] = [
        build_behavior_space_row(
            run_number=run_number,
            parameters=setup_parameters,
            step=0,
            world=world,
        )
    ]

    rng = Random(seed)
    step_limit = _step_limit(setup_parameters, max_steps)
    emitted_step = 0

    while emitted_step < step_limit:
        result = step_fn(world, setup_parameters, rng)
        stopped = bool(getattr(result, "stopped"))
        tick_advanced = bool(getattr(result, "tick_advanced"))

        if tick_advanced:
            emitted_step += 1
            rows.append(
                build_behavior_space_row(
                    run_number=run_number,
                    parameters=setup_parameters,
                    step=emitted_step,
                    world=world,
                )
            )

        if stopped or not tick_advanced:
            break

    return tuple(rows)


def _selected_experiment_spec(experiment: str | ExperimentSpec) -> ExperimentSpec:
    if isinstance(experiment, str):
        return selected_experiment_specs((experiment,))[0]

    selected = SELECTED_EXPERIMENT_REGISTRY.get(experiment.name)
    if selected is None:
        raise ValueError(
            f"Unknown or excluded Slumulation experiment: {experiment.name!r}."
        )
    if selected is not experiment and selected != experiment:
        raise ValueError(
            f"Experiment {experiment.name!r} is not the selected registry spec."
        )
    return selected


def _parameter_source(
    experiment: ExperimentSpec,
    parameter_combination: ParameterCombination | Mapping[str, object] | None,
) -> ParameterCombination | Mapping[str, object]:
    if parameter_combination is not None:
        return parameter_combination
    return experiment.parameter_combinations[0]


def _world_and_parameters(
    setup_result: object,
    fallback_parameters: SetupParameters,
) -> tuple[WorldState, SetupParameters]:
    if isinstance(setup_result, SetupInitialization):
        return setup_result.world, setup_result.parameters
    if isinstance(setup_result, WorldState):
        return setup_result, fallback_parameters
    if hasattr(setup_result, "world"):
        world = getattr(setup_result, "world")
        parameters = getattr(setup_result, "parameters", fallback_parameters)
        if not isinstance(world, WorldState):
            raise TypeError("setup_fn returned an object with a non-WorldState world.")
        return world, load_setup_parameters(parameters)
    raise TypeError("setup_fn must return SetupInitialization or WorldState.")


def _step_limit(parameters: SetupParameters, max_steps: int | None) -> int:
    if max_steps is None:
        return parameters.simulation_runtime
    if max_steps < 0:
        raise ValueError(f"max_steps must be non-negative, got {max_steps}.")
    return min(max_steps, parameters.simulation_runtime)


def write_selected_mesa_surface(
    output_dir: str | PathLike[str],
    *,
    repetitions: int = REFERENCE_REPETITIONS,
    base_seed: int = 20260709,
    max_steps: int | None = None,
):
    """Write the selected Mesa experiment surface to a new directory.

    Importing the batch writer lazily avoids a module cycle because validation
    builds on the single-run functions defined above.
    """

    if repetitions < 1:
        raise ValueError(f"repetitions must be positive, got {repetitions}.")
    if max_steps is not None and max_steps < 0:
        raise ValueError(f"max_steps must be non-negative, got {max_steps}.")
    destination = _create_new_output_directory(output_dir)
    from .validation import write_mesa_validation_outputs

    return write_mesa_validation_outputs(
        destination,
        repetitions=repetitions,
        base_seed=base_seed,
        max_steps=max_steps,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the selected Mesa surface."""

    parser = argparse.ArgumentParser(
        description=(
            "Rerun the selected Slumulation Mesa baseline, politics/developer, "
            "and population-growth conditions."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New directory that will receive the generated CSVs and seed manifest.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=REFERENCE_REPETITIONS,
        help="Repetitions per condition (default: 30).",
    )
    parser.add_argument(
        "--base-seed",
        type=int,
        default=20260709,
        help="Deterministic seed-manifest base seed (default: 20260709).",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Optional reduced horizon for smoke runs; the full horizon is 50.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected Mesa surface command."""

    arguments = build_argument_parser().parse_args(argv)
    result = write_selected_mesa_surface(
        arguments.output_dir,
        repetitions=arguments.repetitions,
        base_seed=arguments.base_seed,
        max_steps=arguments.max_steps,
    )
    for output in result.outputs:
        print(output.output_path)
    if result.manifest_path is not None:
        print(result.manifest_path)
    return 0


def _create_new_output_directory(path: str | PathLike[str]) -> Path:
    destination = Path(path).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Output directory already exists: {destination}.")
    destination.mkdir(parents=True, exist_ok=False)
    return destination


__all__ = [
    "BehaviorSpaceRow",
    "behavior_space_columns",
    "build_behavior_space_row",
    "build_argument_parser",
    "main",
    "metric_values",
    "run_behavior_space_rows",
    "selected_experiment_specs",
    "write_selected_mesa_surface",
    "write_behavior_space_rows",
]


if __name__ == "__main__":
    raise SystemExit(main())
