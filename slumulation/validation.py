from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from os import PathLike
from pathlib import Path
from typing import Any

from .constants import (
    PARAMETER_FIELD_ORDER,
    PRIMARY_VALIDATION_METRICS,
    RAW_ONLY_METRIC_NAMES,
    REFERENCE_REPETITIONS,
    SOURCE_EMITTED_METRIC_NAMES,
    SUPPORTING_METRIC_NAMES,
    ExperimentSpec,
    NetLogoValue,
    ParameterCombination,
)
from .runner import (
    BehaviorSpaceRow,
    behavior_space_columns,
    run_behavior_space_rows,
    selected_experiment_specs,
    write_behavior_space_rows,
)

DEFAULT_MESA_BASE_SEED = 20260709
_MetricGroupKey = tuple[tuple[tuple[str, NetLogoValue], ...], int, str]


@dataclass(frozen=True, slots=True)
class SeedManifestEntry:
    experiment_name: str
    experiment_index: int
    parameter_combination_index: int
    parameter_label: str
    parameter_values: tuple[tuple[str, NetLogoValue], ...]
    repetition_index: int
    run_number: int
    base_seed: int
    seed: int


@dataclass(frozen=True, slots=True)
class SmokeRunResult:
    experiment_name: str
    parameter_label: str
    repetitions: int
    output_path: Path
    manifest_path: Path | None
    row_count: int
    run_count: int
    parameter_condition_count: int
    seed_manifest: tuple[SeedManifestEntry, ...]


@dataclass(frozen=True, slots=True)
class MesaValidationOutput:
    experiment_name: str
    repetitions: int
    output_path: Path
    row_count: int
    run_count: int
    parameter_condition_count: int
    seed_manifest: tuple[SeedManifestEntry, ...]


@dataclass(frozen=True, slots=True)
class MesaValidationOutputsResult:
    output_dir: Path
    manifest_path: Path | None
    repetitions: int
    base_seed: int
    outputs: tuple[MesaValidationOutput, ...]
    seed_manifest: tuple[SeedManifestEntry, ...]


@dataclass(frozen=True, slots=True)
class LoadedBehaviorSpaceTable:
    path: Path
    source: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    metadata_rows: tuple[tuple[str, ...], ...]
    header_line_index: int

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True)
class ShapeCheckSummary:
    source: str
    path: Path
    columns: tuple[str, ...]
    expected_columns: tuple[str, ...]
    column_order_matches: bool
    column_set_matches: bool
    missing_columns: tuple[str, ...]
    extra_columns: tuple[str, ...]
    row_count: int
    run_count: int
    parameter_condition_count: int
    step_min: int | None
    step_max: int | None
    step_values: tuple[int, ...]
    missing_metrics: tuple[str, ...]
    extra_metrics: tuple[str, ...]
    missing_parameter_columns: tuple[str, ...]
    extra_parameter_columns: tuple[str, ...]
    actual_parameter_conditions: tuple[tuple[tuple[str, NetLogoValue], ...], ...]
    expected_parameter_conditions: tuple[tuple[tuple[str, NetLogoValue], ...], ...]
    missing_parameter_conditions: tuple[tuple[tuple[str, NetLogoValue], ...], ...]
    unexpected_parameter_conditions: tuple[tuple[tuple[str, NetLogoValue], ...], ...]


@dataclass(frozen=True, slots=True)
class ShapeComparisonSummary:
    mesa: ShapeCheckSummary
    reference: ShapeCheckSummary
    column_order_matches: bool
    column_set_matches: bool
    row_count_delta: int
    run_count_delta: int
    parameter_condition_count_delta: int
    step_range_matches: bool
    missing_metrics_delta: tuple[str, ...]
    extra_metrics_delta: tuple[str, ...]
    missing_parameter_columns_delta: tuple[str, ...]
    extra_parameter_columns_delta: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ComparisonOutputsResult:
    comparison_dir: Path
    final_step_path: Path
    trajectories_path: Path
    supporting_trajectories_path: Path
    experiments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _MetricDistributionSummary:
    n: int
    finite_n: int
    nonfinite_n: int
    mean: float | None
    stdev: float | None
    minimum: float | None
    q25: float | None
    median: float | None
    q75: float | None
    maximum: float | None


def derive_mesa_seed(
    *,
    experiment_name: str,
    experiment_index: int,
    parameter_combination_index: int,
    parameter_label: str,
    parameter_values: Mapping[str, object] | Iterable[tuple[str, object]],
    repetition_index: int,
    run_number: int,
    base_seed: int = DEFAULT_MESA_BASE_SEED,
) -> int:
    """Derive a deterministic Mesa seed from stable run metadata."""

    payload = {
        "base_seed": base_seed,
        "experiment_name": experiment_name,
        "experiment_index": experiment_index,
        "parameter_combination_index": parameter_combination_index,
        "parameter_label": parameter_label,
        "parameter_values": _stable_parameter_values(parameter_values),
        "repetition_index": repetition_index,
        "run_number": run_number,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).digest()
    return int.from_bytes(digest[:8], byteorder="big") & ((1 << 63) - 1)


def build_seed_manifest(
    experiment: str | ExperimentSpec,
    *,
    repetitions: int = 1,
    base_seed: int = DEFAULT_MESA_BASE_SEED,
    parameter_combination_index: int | None = None,
    experiment_index: int = 0,
    run_number_start: int = 1,
) -> tuple[SeedManifestEntry, ...]:
    """Build deterministic seed metadata for one selected experiment."""

    if repetitions < 1:
        raise ValueError(f"repetitions must be positive, got {repetitions}.")

    experiment_spec = _selected_experiment_spec(experiment)
    parameter_combinations = _selected_parameter_combinations(
        experiment_spec,
        parameter_combination_index,
    )

    entries: list[SeedManifestEntry] = []
    run_number = run_number_start
    for resolved_index, parameter_combination in parameter_combinations:
        parameter_values = _stable_parameter_values(parameter_combination.values)
        for repetition_index in range(1, repetitions + 1):
            seed = derive_mesa_seed(
                experiment_name=experiment_spec.name,
                experiment_index=experiment_index,
                parameter_combination_index=resolved_index,
                parameter_label=parameter_combination.label,
                parameter_values=parameter_values,
                repetition_index=repetition_index,
                run_number=run_number,
                base_seed=base_seed,
            )
            entries.append(
                SeedManifestEntry(
                    experiment_name=experiment_spec.name,
                    experiment_index=experiment_index,
                    parameter_combination_index=resolved_index,
                    parameter_label=parameter_combination.label,
                    parameter_values=parameter_values,
                    repetition_index=repetition_index,
                    run_number=run_number,
                    base_seed=base_seed,
                    seed=seed,
                )
            )
            run_number += 1

    return tuple(entries)


def write_mesa_smoke_output(
    output_path: str | PathLike[str],
    *,
    experiment: str | ExperimentSpec = "Typical Run",
    parameter_combination_index: int = 0,
    repetitions: int = 1,
    base_seed: int = DEFAULT_MESA_BASE_SEED,
    max_steps: int | None = None,
    manifest_path: str | PathLike[str] | None = None,
    write_manifest: bool = True,
) -> SmokeRunResult:
    """Write a bounded one-condition Mesa smoke CSV and return its seed manifest."""

    output = Path(output_path)
    experiment_spec = _selected_experiment_spec(experiment)
    parameter_combinations = _selected_parameter_combinations(
        experiment_spec,
        parameter_combination_index,
    )
    if len(parameter_combinations) != 1:
        raise RuntimeError(
            "Smoke output must resolve to exactly one parameter condition."
        )

    _, parameter_combination = parameter_combinations[0]
    seed_manifest = build_seed_manifest(
        experiment_spec,
        repetitions=repetitions,
        base_seed=base_seed,
        parameter_combination_index=parameter_combination_index,
    )

    rows: list[BehaviorSpaceRow] = []
    for entry in seed_manifest:
        rows.extend(
            run_behavior_space_rows(
                experiment_spec,
                parameter_combination=parameter_combination,
                run_number=entry.run_number,
                seed=entry.seed,
                max_steps=max_steps,
            )
        )

    write_behavior_space_rows(output, rows)

    resolved_manifest_path: Path | None = None
    if write_manifest:
        resolved_manifest_path = (
            Path(manifest_path)
            if manifest_path is not None
            else output.with_suffix(f"{output.suffix}.seed_manifest.json")
        )
        _write_seed_manifest(resolved_manifest_path, seed_manifest)
    elif manifest_path is not None:
        raise ValueError("manifest_path was provided but write_manifest is False.")

    return SmokeRunResult(
        experiment_name=experiment_spec.name,
        parameter_label=parameter_combination.label,
        repetitions=repetitions,
        output_path=output,
        manifest_path=resolved_manifest_path,
        row_count=len(rows),
        run_count=len({entry.run_number for entry in seed_manifest}),
        parameter_condition_count=1,
        seed_manifest=seed_manifest,
    )


def write_mesa_validation_outputs(
    output_dir: str | PathLike[str],
    *,
    experiment_names: Iterable[str] | None = None,
    selected_experiment_names: Iterable[str] | None = None,
    repetitions: int = REFERENCE_REPETITIONS,
    repetition_count: int | None = None,
    base_seed: int = DEFAULT_MESA_BASE_SEED,
    max_steps: int | None = None,
    manifest_path: str | PathLike[str] | None = None,
    write_manifest: bool = True,
    run_rows_fn=None,
    run_behavior_space_rows_fn=None,
    write_rows_fn=None,
    write_behavior_space_rows_fn=None,
) -> MesaValidationOutputsResult:
    """Write one bounded Mesa validation CSV per selected experiment.

    The raw CSVs keep the fixed 32-column BehaviorSpace-compatible schema. Mesa
    seed metadata is written only to the sidecar manifest when requested.
    """

    if repetition_count is not None:
        if repetitions != REFERENCE_REPETITIONS and repetitions != repetition_count:
            raise ValueError(
                "repetitions and repetition_count specify different values."
            )
        repetitions = repetition_count
    if repetitions < 1:
        raise ValueError(f"repetitions must be positive, got {repetitions}.")

    selected_names = _coalesced_experiment_names(
        experiment_names,
        selected_experiment_names,
    )
    experiment_specs = selected_experiment_specs(selected_names)
    if not experiment_specs:
        raise ValueError("At least one selected experiment is required.")

    output_directory = Path(output_dir)
    output_directory.mkdir(parents=True, exist_ok=True)

    run_rows = run_rows_fn or run_behavior_space_rows_fn or run_behavior_space_rows
    write_rows = (
        write_rows_fn or write_behavior_space_rows_fn or write_behavior_space_rows
    )
    experiment_indexes = _selected_experiment_index_by_name()

    outputs: list[MesaValidationOutput] = []
    all_seed_manifest_entries: list[SeedManifestEntry] = []

    for experiment_spec in experiment_specs:
        experiment_index = experiment_indexes[experiment_spec.name]
        seed_manifest = build_seed_manifest(
            experiment_spec,
            repetitions=repetitions,
            base_seed=base_seed,
            experiment_index=experiment_index,
        )
        parameter_combinations = dict(
            _selected_parameter_combinations(experiment_spec, None)
        )

        rows: list[BehaviorSpaceRow] = []
        for entry in seed_manifest:
            rows.extend(
                run_rows(
                    experiment_spec,
                    parameter_combination=parameter_combinations[
                        entry.parameter_combination_index
                    ],
                    run_number=entry.run_number,
                    seed=entry.seed,
                    max_steps=max_steps,
                )
            )

        output_path = output_directory / _mesa_validation_csv_name(
            experiment_spec,
            repetitions,
        )
        write_rows(output_path, rows)

        outputs.append(
            MesaValidationOutput(
                experiment_name=experiment_spec.name,
                repetitions=repetitions,
                output_path=output_path,
                row_count=len(rows),
                run_count=len({entry.run_number for entry in seed_manifest}),
                parameter_condition_count=len(experiment_spec.parameter_combinations),
                seed_manifest=seed_manifest,
            )
        )
        all_seed_manifest_entries.extend(seed_manifest)

    resolved_manifest_path: Path | None = None
    if write_manifest:
        resolved_manifest_path = (
            Path(manifest_path)
            if manifest_path is not None
            else output_directory / "seeds.json"
        )
        resolved_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        _write_seed_manifest(
            resolved_manifest_path,
            tuple(all_seed_manifest_entries),
        )
    elif manifest_path is not None:
        raise ValueError("manifest_path was provided but write_manifest is False.")

    return MesaValidationOutputsResult(
        output_dir=output_directory,
        manifest_path=resolved_manifest_path,
        repetitions=repetitions,
        base_seed=base_seed,
        outputs=tuple(outputs),
        seed_manifest=tuple(all_seed_manifest_entries),
    )


def load_mesa_csv(path: str | PathLike[str]) -> LoadedBehaviorSpaceTable:
    """Load a simple Mesa CSV written by write_behavior_space_rows."""

    csv_path = Path(path)
    raw_rows = _read_csv_rows(csv_path)
    if not raw_rows:
        raise ValueError(f"Mesa CSV is empty: {csv_path}.")

    columns = tuple(raw_rows[0])
    if columns != behavior_space_columns():
        raise ValueError(
            f"Mesa CSV header does not match BehaviorSpace columns: {csv_path}."
        )

    rows = _dict_rows(csv_path, columns, raw_rows[1:], start_line_number=2)
    return LoadedBehaviorSpaceTable(
        path=csv_path,
        source="mesa",
        columns=columns,
        rows=rows,
        metadata_rows=(),
        header_line_index=0,
    )


def load_netlogo_behavior_space_table(
    path: str | PathLike[str],
) -> LoadedBehaviorSpaceTable:
    """Load a NetLogo BehaviorSpace table with metadata lines before the header."""

    csv_path = Path(path)
    raw_rows = _read_csv_rows(csv_path)
    header_line_index = _find_behavior_space_header(csv_path, raw_rows)
    columns = tuple(raw_rows[header_line_index])
    metadata_rows = tuple(tuple(row) for row in raw_rows[:header_line_index])
    rows = _dict_rows(
        csv_path,
        columns,
        raw_rows[header_line_index + 1 :],
        start_line_number=header_line_index + 2,
    )

    return LoadedBehaviorSpaceTable(
        path=csv_path,
        source="netlogo",
        columns=columns,
        rows=rows,
        metadata_rows=metadata_rows,
        header_line_index=header_line_index,
    )


def summarize_table_shape(
    table: LoadedBehaviorSpaceTable,
    *,
    expected_columns: Sequence[str] | None = None,
    metric_columns: Sequence[str] = SOURCE_EMITTED_METRIC_NAMES,
    parameter_columns: Sequence[str] = PARAMETER_FIELD_ORDER,
    expected_parameter_conditions: (
        Sequence[Mapping[str, object] | Iterable[tuple[str, object]]] | None
    ) = None,
) -> ShapeCheckSummary:
    """Summarize table shape only, without decision rules."""

    expected = tuple(
        expected_columns if expected_columns is not None else behavior_space_columns()
    )
    metrics = tuple(metric_columns)
    parameters = tuple(parameter_columns)
    columns = table.columns

    missing_columns = tuple(column for column in expected if column not in columns)
    extra_columns = tuple(column for column in columns if column not in expected)
    step_values = _step_values(table.rows)
    run_count = _unique_value_count(table.rows, "[run number]")
    parameter_condition_count = _parameter_condition_count(table.rows, parameters)
    actual_parameter_columns = _actual_parameter_columns(columns)
    available_selected_parameter_columns = tuple(
        parameter for parameter in parameters if parameter in actual_parameter_columns
    )
    actual_parameter_conditions = _actual_parameter_conditions(
        table.rows,
        available_selected_parameter_columns,
    )
    normalized_expected_parameter_conditions = _expected_parameter_conditions(
        expected_parameter_conditions,
        available_selected_parameter_columns,
    )

    known_non_metric_columns = {"[run number]", "[step]", *parameters}
    extra_metrics = tuple(
        column
        for column in columns
        if column not in known_non_metric_columns and column not in metrics
    )

    return ShapeCheckSummary(
        source=table.source,
        path=table.path,
        columns=columns,
        expected_columns=expected,
        column_order_matches=columns == expected,
        column_set_matches=set(columns) == set(expected),
        missing_columns=missing_columns,
        extra_columns=extra_columns,
        row_count=table.row_count,
        run_count=run_count,
        parameter_condition_count=parameter_condition_count,
        step_min=step_values[0] if step_values else None,
        step_max=step_values[-1] if step_values else None,
        step_values=step_values,
        missing_metrics=tuple(metric for metric in metrics if metric not in columns),
        extra_metrics=extra_metrics,
        missing_parameter_columns=tuple(
            parameter
            for parameter in parameters
            if parameter not in actual_parameter_columns
        ),
        extra_parameter_columns=tuple(
            parameter
            for parameter in actual_parameter_columns
            if parameter not in parameters
        ),
        actual_parameter_conditions=actual_parameter_conditions,
        expected_parameter_conditions=normalized_expected_parameter_conditions,
        missing_parameter_conditions=tuple(
            condition
            for condition in normalized_expected_parameter_conditions
            if condition not in actual_parameter_conditions
        ),
        unexpected_parameter_conditions=tuple(
            condition
            for condition in actual_parameter_conditions
            if normalized_expected_parameter_conditions
            and condition not in normalized_expected_parameter_conditions
        ),
    )


def compare_table_shapes(
    mesa: LoadedBehaviorSpaceTable | ShapeCheckSummary,
    reference: LoadedBehaviorSpaceTable | ShapeCheckSummary,
) -> ShapeComparisonSummary:
    """Compare two shape summaries descriptively, without decision rules."""

    mesa_summary = (
        mesa if isinstance(mesa, ShapeCheckSummary) else summarize_table_shape(mesa)
    )
    reference_summary = (
        reference
        if isinstance(reference, ShapeCheckSummary)
        else summarize_table_shape(reference)
    )

    return ShapeComparisonSummary(
        mesa=mesa_summary,
        reference=reference_summary,
        column_order_matches=mesa_summary.columns == reference_summary.columns,
        column_set_matches=set(mesa_summary.columns) == set(reference_summary.columns),
        row_count_delta=mesa_summary.row_count - reference_summary.row_count,
        run_count_delta=mesa_summary.run_count - reference_summary.run_count,
        parameter_condition_count_delta=(
            mesa_summary.parameter_condition_count
            - reference_summary.parameter_condition_count
        ),
        step_range_matches=(
            mesa_summary.step_min,
            mesa_summary.step_max,
        )
        == (
            reference_summary.step_min,
            reference_summary.step_max,
        ),
        missing_metrics_delta=_tuple_delta(
            mesa_summary.missing_metrics,
            reference_summary.missing_metrics,
        ),
        extra_metrics_delta=_tuple_delta(
            mesa_summary.extra_metrics,
            reference_summary.extra_metrics,
        ),
        missing_parameter_columns_delta=_tuple_delta(
            mesa_summary.missing_parameter_columns,
            reference_summary.missing_parameter_columns,
        ),
        extra_parameter_columns_delta=_tuple_delta(
            mesa_summary.extra_parameter_columns,
            reference_summary.extra_parameter_columns,
        ),
    )


def write_comparison_outputs(
    mesa_output_dir: str | PathLike[str],
    comparison_dir: str | PathLike[str],
    *,
    experiment_names: Iterable[str] | None = None,
    selected_experiment_names: Iterable[str] | None = None,
    repetitions: int = REFERENCE_REPETITIONS,
    netlogo_reference_dir: str | PathLike[str] | None = None,
    mesa_paths: Mapping[str, str | PathLike[str]] | None = None,
    netlogo_paths: Mapping[str, str | PathLike[str]] | None = None,
) -> ComparisonOutputsResult:
    """Write diagnostic Mesa-vs-NetLogo comparison summaries.

    Summaries align independent repetitions by experiment, parameter condition,
    step, and metric. They intentionally stay descriptive and avoid claim labels.
    """

    selected_names = _coalesced_experiment_names(
        experiment_names,
        selected_experiment_names,
    )
    experiment_specs = selected_experiment_specs(selected_names)
    if not experiment_specs:
        raise ValueError("At least one selected experiment is required.")

    mesa_directory = Path(mesa_output_dir)
    comparison_directory = Path(comparison_dir)
    comparison_directory.mkdir(parents=True, exist_ok=True)

    final_step_rows: list[dict[str, object]] = []
    trajectory_rows: list[dict[str, object]] = []
    supporting_raw_rows: list[dict[str, object]] = []
    supporting_raw_metrics = tuple(SUPPORTING_METRIC_NAMES + RAW_ONLY_METRIC_NAMES)
    supporting_raw_categories = {
        **{metric: "supporting" for metric in SUPPORTING_METRIC_NAMES},
        **{metric: "raw_only" for metric in RAW_ONLY_METRIC_NAMES},
    }

    for experiment_spec in experiment_specs:
        mesa_path = _resolve_mesa_table_path(
            experiment_spec,
            mesa_directory,
            repetitions,
            mesa_paths,
        )
        reference_path = _resolve_netlogo_table_path(
            experiment_spec,
            netlogo_reference_dir,
            netlogo_paths,
        )
        mesa_table = load_mesa_csv(mesa_path)
        reference_table = load_netlogo_behavior_space_table(reference_path)

        final_step_rows.extend(
            _metric_comparison_rows(
                experiment_spec,
                mesa_table,
                reference_table,
                metrics=PRIMARY_VALIDATION_METRICS,
                steps=(experiment_spec.step_max,),
            )
        )
        trajectory_rows.extend(
            _metric_comparison_rows(
                experiment_spec,
                mesa_table,
                reference_table,
                metrics=PRIMARY_VALIDATION_METRICS,
                steps=_experiment_steps(experiment_spec),
            )
        )
        supporting_raw_rows.extend(
            _metric_comparison_rows(
                experiment_spec,
                mesa_table,
                reference_table,
                metrics=supporting_raw_metrics,
                steps=_experiment_steps(experiment_spec),
                metric_categories=supporting_raw_categories,
            )
        )

    final_step_path = comparison_directory / "final_step.csv"
    trajectory_path = comparison_directory / "trajectories.csv"
    supporting_raw_path = comparison_directory / "supporting_trajectories.csv"

    _write_dict_csv(final_step_path, _metric_summary_columns(), final_step_rows)
    _write_dict_csv(trajectory_path, _metric_summary_columns(), trajectory_rows)
    _write_dict_csv(
        supporting_raw_path,
        _metric_summary_columns(include_metric_category=True),
        supporting_raw_rows,
    )

    return ComparisonOutputsResult(
        comparison_dir=comparison_directory,
        final_step_path=final_step_path,
        trajectories_path=trajectory_path,
        supporting_trajectories_path=supporting_raw_path,
        experiments=tuple(experiment.name for experiment in experiment_specs),
    )


def _selected_experiment_spec(experiment: str | ExperimentSpec) -> ExperimentSpec:
    if isinstance(experiment, str):
        return selected_experiment_specs((experiment,))[0]

    selected = selected_experiment_specs((experiment.name,))[0]
    if selected is not experiment and selected != experiment:
        raise ValueError(
            f"Experiment {experiment.name!r} is not the selected registry spec."
        )
    return selected


def _selected_parameter_combinations(
    experiment: ExperimentSpec,
    parameter_combination_index: int | None,
) -> tuple[tuple[int, ParameterCombination], ...]:
    if parameter_combination_index is None:
        return tuple(enumerate(experiment.parameter_combinations))

    if parameter_combination_index < 0:
        raise ValueError(
            f"parameter_combination_index must be non-negative, "
            f"got {parameter_combination_index}."
        )
    try:
        parameter_combination = experiment.parameter_combinations[
            parameter_combination_index
        ]
    except IndexError as exc:
        raise ValueError(
            f"Experiment {experiment.name!r} has no parameter combination at "
            f"index {parameter_combination_index}."
        ) from exc
    return ((parameter_combination_index, parameter_combination),)


def _stable_parameter_values(
    values: Mapping[str, object] | Iterable[tuple[str, object]],
) -> tuple[tuple[str, NetLogoValue], ...]:
    if isinstance(values, Mapping):
        items = []
        for name in PARAMETER_FIELD_ORDER:
            if name in values:
                items.append((name, values[name]))
        items.extend(
            (name, value)
            for name, value in sorted(values.items())
            if name not in PARAMETER_FIELD_ORDER
        )
    else:
        items = list(values)

    return tuple((str(name), _netlogo_value(value)) for name, value in items)


def _netlogo_value(value: object) -> NetLogoValue:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        return value
    raise TypeError(f"Unsupported seed-manifest parameter value: {value!r}.")


def _write_seed_manifest(
    path: Path,
    entries: tuple[SeedManifestEntry, ...],
) -> None:
    payload: dict[str, Any] = {
        "schema": "yatasterps.slumulation.seed_manifest.v1",
        "base_seed": entries[0].base_seed if entries else DEFAULT_MESA_BASE_SEED,
        "entries": [asdict(entry) for entry in entries],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _coalesced_experiment_names(
    *experiment_name_sets: Iterable[str] | None,
) -> tuple[str, ...] | None:
    provided = [
        tuple(experiment_names)
        for experiment_names in experiment_name_sets
        if experiment_names is not None
    ]
    if not provided:
        return None

    first = provided[0]
    for experiment_names in provided[1:]:
        if experiment_names != first:
            raise ValueError("Conflicting selected experiment name arguments.")
    return first


def _selected_experiment_index_by_name() -> dict[str, int]:
    return {
        experiment.name: index
        for index, experiment in enumerate(selected_experiment_specs())
    }


def _mesa_validation_csv_name(
    experiment: ExperimentSpec,
    repetitions: int,
) -> str:
    del repetitions
    return experiment.reference_raw_table.name


def _resolve_mesa_table_path(
    experiment: ExperimentSpec,
    mesa_output_dir: Path,
    repetitions: int,
    mesa_paths: Mapping[str, str | PathLike[str]] | None,
) -> Path:
    if mesa_paths is not None and experiment.name in mesa_paths:
        return Path(mesa_paths[experiment.name])
    return mesa_output_dir / _mesa_validation_csv_name(experiment, repetitions)


def _resolve_netlogo_table_path(
    experiment: ExperimentSpec,
    netlogo_reference_dir: str | PathLike[str] | None,
    netlogo_paths: Mapping[str, str | PathLike[str]] | None,
) -> Path:
    if netlogo_paths is not None and experiment.name in netlogo_paths:
        return Path(netlogo_paths[experiment.name])
    if netlogo_reference_dir is not None:
        return Path(netlogo_reference_dir) / experiment.reference_raw_table.name
    return experiment.reference_raw_table


def _experiment_steps(experiment: ExperimentSpec) -> tuple[int, ...]:
    return tuple(range(experiment.step_min, experiment.step_max + 1))


def _read_csv_rows(path: Path) -> list[list[str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


def _find_behavior_space_header(path: Path, rows: Sequence[Sequence[str]]) -> int:
    expected = behavior_space_columns()
    for index, row in enumerate(rows):
        columns = tuple(row)
        if columns == expected:
            return index
        if columns and columns[0] == "[run number]" and "[step]" in columns:
            return index
    raise ValueError(f"No BehaviorSpace data header found in {path}.")


def _dict_rows(
    path: Path,
    columns: tuple[str, ...],
    rows: Sequence[Sequence[str]],
    *,
    start_line_number: int,
) -> tuple[dict[str, str], ...]:
    loaded_rows: list[dict[str, str]] = []
    for offset, row in enumerate(rows):
        line_number = start_line_number + offset
        if not row:
            continue
        if len(row) != len(columns):
            raise ValueError(
                f"CSV row {line_number} in {path} has {len(row)} columns; "
                f"expected {len(columns)}."
            )
        loaded_rows.append(dict(zip(columns, row, strict=True)))
    return tuple(loaded_rows)


def _step_values(rows: Sequence[Mapping[str, str]]) -> tuple[int, ...]:
    if not rows or "[step]" not in rows[0]:
        return ()
    return tuple(
        sorted(
            {
                int(_normalized_cell(row["[step]"]))
                for row in rows
                if row.get("[step]", "") != ""
            }
        )
    )


def _unique_value_count(rows: Sequence[Mapping[str, str]], column: str) -> int:
    if not rows or column not in rows[0]:
        return 0
    return len({_normalized_cell(row[column]) for row in rows})


def _parameter_condition_count(
    rows: Sequence[Mapping[str, str]],
    parameter_columns: tuple[str, ...],
) -> int:
    if not rows:
        return 0
    available_parameters = tuple(
        parameter for parameter in parameter_columns if parameter in rows[0]
    )
    if not available_parameters:
        return 0
    return len(
        {
            tuple(
                _normalized_cell(row[parameter]) for parameter in available_parameters
            )
            for row in rows
        }
    )


def _actual_parameter_conditions(
    rows: Sequence[Mapping[str, str]],
    parameter_columns: tuple[str, ...],
) -> tuple[tuple[tuple[str, NetLogoValue], ...], ...]:
    if not rows or not parameter_columns:
        return ()

    conditions = {
        tuple(
            (parameter, _netlogo_value(_normalized_cell(row[parameter])))
            for parameter in parameter_columns
        )
        for row in rows
    }
    return tuple(sorted(conditions, key=repr))


def _expected_parameter_conditions(
    expected_parameter_conditions: (
        Sequence[Mapping[str, object] | Iterable[tuple[str, object]]] | None
    ),
    parameter_columns: tuple[str, ...],
) -> tuple[tuple[tuple[str, NetLogoValue], ...], ...]:
    if expected_parameter_conditions is None:
        return ()

    conditions = tuple(
        _normalize_parameter_condition(condition, parameter_columns)
        for condition in expected_parameter_conditions
    )
    return tuple(sorted(set(conditions), key=repr))


def _normalize_parameter_condition(
    condition: Mapping[str, object] | Iterable[tuple[str, object]],
    parameter_columns: tuple[str, ...],
) -> tuple[tuple[str, NetLogoValue], ...]:
    if isinstance(condition, Mapping):
        return tuple(
            (parameter, _netlogo_value(condition[parameter]))
            for parameter in parameter_columns
            if parameter in condition
        )

    values = dict(condition)
    return tuple(
        (parameter, _netlogo_value(values[parameter]))
        for parameter in parameter_columns
        if parameter in values
    )


def _normalized_cell(value: str) -> bool | int | float | str:
    stripped = value.strip()
    lowered = stripped.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        return stripped


def _actual_parameter_columns(columns: tuple[str, ...]) -> tuple[str, ...]:
    try:
        run_number_index = columns.index("[run number]")
        step_index = columns.index("[step]")
    except ValueError:
        return tuple(column for column in columns if column in PARAMETER_FIELD_ORDER)
    return columns[run_number_index + 1 : step_index]


def _tuple_delta(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(value for value in left if value not in right)


def _shape_comparison_row(
    experiment: ExperimentSpec,
    comparison: ShapeComparisonSummary,
) -> dict[str, object]:
    mesa = comparison.mesa
    reference = comparison.reference
    return {
        "experiment": experiment.name,
        "mesa_path": mesa.path,
        "reference_path": reference.path,
        "mesa_row_count": mesa.row_count,
        "reference_row_count": reference.row_count,
        "row_count_delta": comparison.row_count_delta,
        "mesa_run_count": mesa.run_count,
        "reference_run_count": reference.run_count,
        "run_count_delta": comparison.run_count_delta,
        "mesa_parameter_condition_count": mesa.parameter_condition_count,
        "reference_parameter_condition_count": reference.parameter_condition_count,
        "parameter_condition_count_delta": (comparison.parameter_condition_count_delta),
        "mesa_step_min": mesa.step_min,
        "mesa_step_max": mesa.step_max,
        "reference_step_min": reference.step_min,
        "reference_step_max": reference.step_max,
        "step_range_matches": comparison.step_range_matches,
        "column_order_matches": comparison.column_order_matches,
        "column_set_matches": comparison.column_set_matches,
        "mesa_missing_columns": _json_cell(mesa.missing_columns),
        "reference_missing_columns": _json_cell(reference.missing_columns),
        "mesa_extra_columns": _json_cell(mesa.extra_columns),
        "reference_extra_columns": _json_cell(reference.extra_columns),
        "mesa_missing_metrics": _json_cell(mesa.missing_metrics),
        "reference_missing_metrics": _json_cell(reference.missing_metrics),
        "mesa_extra_metrics": _json_cell(mesa.extra_metrics),
        "reference_extra_metrics": _json_cell(reference.extra_metrics),
        "mesa_missing_parameter_conditions": _conditions_cell(
            mesa.missing_parameter_conditions
        ),
        "reference_missing_parameter_conditions": _conditions_cell(
            reference.missing_parameter_conditions
        ),
        "mesa_unexpected_parameter_conditions": _conditions_cell(
            mesa.unexpected_parameter_conditions
        ),
        "reference_unexpected_parameter_conditions": _conditions_cell(
            reference.unexpected_parameter_conditions
        ),
    }


def _shape_summary_columns() -> tuple[str, ...]:
    return (
        "experiment",
        "mesa_path",
        "reference_path",
        "mesa_row_count",
        "reference_row_count",
        "row_count_delta",
        "mesa_run_count",
        "reference_run_count",
        "run_count_delta",
        "mesa_parameter_condition_count",
        "reference_parameter_condition_count",
        "parameter_condition_count_delta",
        "mesa_step_min",
        "mesa_step_max",
        "reference_step_min",
        "reference_step_max",
        "step_range_matches",
        "column_order_matches",
        "column_set_matches",
        "mesa_missing_columns",
        "reference_missing_columns",
        "mesa_extra_columns",
        "reference_extra_columns",
        "mesa_missing_metrics",
        "reference_missing_metrics",
        "mesa_extra_metrics",
        "reference_extra_metrics",
        "mesa_missing_parameter_conditions",
        "reference_missing_parameter_conditions",
        "mesa_unexpected_parameter_conditions",
        "reference_unexpected_parameter_conditions",
    )


def _metric_comparison_rows(
    experiment: ExperimentSpec,
    mesa_table: LoadedBehaviorSpaceTable,
    reference_table: LoadedBehaviorSpaceTable,
    *,
    metrics: Sequence[str],
    steps: Sequence[int],
    metric_categories: Mapping[str, str] | None = None,
) -> tuple[dict[str, object], ...]:
    metric_names = tuple(metrics)
    expected_conditions = tuple(
        _stable_parameter_values(parameter_combination.values)
        for parameter_combination in experiment.parameter_combinations
    )
    requested_steps = tuple(steps)
    netlogo_summaries = _metric_summaries_by_group(
        reference_table.rows,
        metric_names,
    )
    mesa_summaries = _metric_summaries_by_group(
        mesa_table.rows,
        metric_names,
    )

    expected_keys = {
        (condition, step, metric)
        for condition in expected_conditions
        for step in requested_steps
        for metric in metric_names
    }
    actual_keys = {
        key
        for key in set(netlogo_summaries) | set(mesa_summaries)
        if key[1] in requested_steps and key[2] in metric_names
    }

    rows: list[dict[str, object]] = []
    for condition, step, metric in sorted(
        expected_keys | actual_keys,
        key=_metric_group_sort_key,
    ):
        row: dict[str, object] = {
            "experiment": experiment.name,
            "parameter_condition": _parameter_condition_label(condition),
            "step": step,
            "metric": metric,
        }
        if metric_categories is not None:
            row["metric_category"] = metric_categories.get(metric, "")

        for parameter_name in PARAMETER_FIELD_ORDER:
            row[parameter_name] = _condition_value(condition, parameter_name)

        netlogo_summary = netlogo_summaries.get((condition, step, metric))
        mesa_summary = mesa_summaries.get((condition, step, metric))
        _add_metric_summary_cells(row, "netlogo", netlogo_summary)
        _add_metric_summary_cells(row, "mesa", mesa_summary)
        _add_metric_delta_cells(row, netlogo_summary, mesa_summary)
        rows.append(row)

    return tuple(rows)


def _metric_summaries_by_group(
    rows: Sequence[Mapping[str, str]],
    metrics: tuple[str, ...],
) -> dict[_MetricGroupKey, _MetricDistributionSummary]:
    values_by_group: dict[_MetricGroupKey, list[float | None]] = {}
    for row in rows:
        if "[step]" not in row:
            continue
        condition = _row_parameter_condition(row)
        step = int(_normalized_cell(row["[step]"]))
        for metric in metrics:
            if metric not in row:
                continue
            values_by_group.setdefault((condition, step, metric), []).append(
                _numeric_cell(row[metric])
            )

    return {
        key: _metric_distribution_summary(values)
        for key, values in values_by_group.items()
    }


def _row_parameter_condition(
    row: Mapping[str, str],
) -> tuple[tuple[str, NetLogoValue], ...]:
    return tuple(
        (parameter, _netlogo_value(_normalized_cell(row[parameter])))
        for parameter in PARAMETER_FIELD_ORDER
        if parameter in row
    )


def _metric_distribution_summary(
    values: Sequence[float | None],
) -> _MetricDistributionSummary:
    finite_values = sorted(
        value for value in values if value is not None and math.isfinite(value)
    )
    finite_n = len(finite_values)
    nonfinite_n = len(values) - finite_n

    if not finite_values:
        return _MetricDistributionSummary(
            n=len(values),
            finite_n=0,
            nonfinite_n=nonfinite_n,
            mean=None,
            stdev=None,
            minimum=None,
            q25=None,
            median=None,
            q75=None,
            maximum=None,
        )

    mean = sum(finite_values) / finite_n
    stdev = (
        math.sqrt(sum((value - mean) ** 2 for value in finite_values) / (finite_n - 1))
        if finite_n > 1
        else None
    )
    return _MetricDistributionSummary(
        n=len(values),
        finite_n=finite_n,
        nonfinite_n=nonfinite_n,
        mean=mean,
        stdev=stdev,
        minimum=finite_values[0],
        q25=_quantile(finite_values, 0.25),
        median=_quantile(finite_values, 0.5),
        q75=_quantile(finite_values, 0.75),
        maximum=finite_values[-1],
    )


def _quantile(sorted_values: Sequence[float], probability: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]

    position = (len(sorted_values) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return sorted_values[lower_index]

    lower = sorted_values[lower_index]
    upper = sorted_values[upper_index]
    return lower + (upper - lower) * (position - lower_index)


def _numeric_cell(value: object) -> float | None:
    if value is None:
        return None
    stripped = str(value).strip()
    if stripped == "":
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def _add_metric_summary_cells(
    row: dict[str, object],
    prefix: str,
    summary: _MetricDistributionSummary | None,
) -> None:
    row[f"{prefix}_n"] = summary.n if summary is not None else 0
    row[f"{prefix}_finite_n"] = summary.finite_n if summary is not None else 0
    row[f"{prefix}_nonfinite_n"] = summary.nonfinite_n if summary is not None else 0
    row[f"{prefix}_mean"] = _summary_value(summary.mean if summary else None)
    row[f"{prefix}_stdev"] = _summary_value(summary.stdev if summary else None)
    row[f"{prefix}_min"] = _summary_value(summary.minimum if summary else None)
    row[f"{prefix}_q25"] = _summary_value(summary.q25 if summary else None)
    row[f"{prefix}_median"] = _summary_value(summary.median if summary else None)
    row[f"{prefix}_q75"] = _summary_value(summary.q75 if summary else None)
    row[f"{prefix}_max"] = _summary_value(summary.maximum if summary else None)


def _add_metric_delta_cells(
    row: dict[str, object],
    netlogo: _MetricDistributionSummary | None,
    mesa: _MetricDistributionSummary | None,
) -> None:
    netlogo_mean = netlogo.mean if netlogo is not None else None
    mesa_mean = mesa.mean if mesa is not None else None
    if netlogo_mean is None or mesa_mean is None:
        row["mean_difference_mesa_minus_netlogo"] = ""
        row["absolute_mean_difference"] = ""
        row["relative_mean_difference"] = ""
        return

    difference = mesa_mean - netlogo_mean
    row["mean_difference_mesa_minus_netlogo"] = difference
    row["absolute_mean_difference"] = abs(difference)
    row["relative_mean_difference"] = (
        difference / abs(netlogo_mean) if netlogo_mean != 0 else ""
    )


def _summary_value(value: float | None) -> float | str:
    return "" if value is None else value


def _metric_summary_columns(
    *,
    include_metric_category: bool = False,
) -> tuple[str, ...]:
    leading = (
        "experiment",
        "parameter_condition",
        *PARAMETER_FIELD_ORDER,
        "step",
        "metric",
    )
    if include_metric_category:
        leading = (*leading, "metric_category")
    return (
        *leading,
        "netlogo_n",
        "netlogo_finite_n",
        "netlogo_nonfinite_n",
        "netlogo_mean",
        "netlogo_stdev",
        "netlogo_min",
        "netlogo_q25",
        "netlogo_median",
        "netlogo_q75",
        "netlogo_max",
        "mesa_n",
        "mesa_finite_n",
        "mesa_nonfinite_n",
        "mesa_mean",
        "mesa_stdev",
        "mesa_min",
        "mesa_q25",
        "mesa_median",
        "mesa_q75",
        "mesa_max",
        "mean_difference_mesa_minus_netlogo",
        "absolute_mean_difference",
        "relative_mean_difference",
    )


def _metric_group_sort_key(
    key: tuple[tuple[tuple[str, NetLogoValue], ...], int, str],
) -> tuple[str, int, str]:
    condition, step, metric = key
    return (_parameter_condition_label(condition), step, metric)


def _parameter_condition_label(
    condition: tuple[tuple[str, NetLogoValue], ...],
) -> str:
    return ";".join(f"{name}={value}" for name, value in condition)


def _condition_value(
    condition: tuple[tuple[str, NetLogoValue], ...],
    parameter_name: str,
) -> NetLogoValue | str:
    values = dict(condition)
    return values.get(parameter_name, "")


def _conditions_cell(
    conditions: tuple[tuple[tuple[str, NetLogoValue], ...], ...],
) -> str:
    return _json_cell([dict(condition) for condition in conditions])


def _json_cell(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _write_dict_csv(
    path: Path,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for NetLogo--Mesa CSV summaries."""

    parser = argparse.ArgumentParser(
        description=(
            "Generate descriptive Slumulation CSV summaries from NetLogo and "
            "Mesa run outputs."
        )
    )
    parser.add_argument(
        "--mesa-dir",
        type=Path,
        required=True,
        help="Directory containing baseline, politics/development, and population-growth CSVs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New directory that will receive the generated summary CSVs.",
    )
    parser.add_argument(
        "--netlogo-dir",
        type=Path,
        default=None,
        help="Optional directory containing matching NetLogo CSVs.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=REFERENCE_REPETITIONS,
        help="Repetitions represented by each Mesa condition (default: 30).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Generate descriptive comparison summaries from existing run outputs."""

    arguments = build_argument_parser().parse_args(argv)
    output_dir = arguments.output_dir.expanduser().resolve()
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}.")
    result = write_comparison_outputs(
        arguments.mesa_dir,
        output_dir,
        repetitions=arguments.repetitions,
        netlogo_reference_dir=arguments.netlogo_dir,
    )
    print(result.final_step_path)
    print(result.trajectories_path)
    print(result.supporting_trajectories_path)
    return 0


__all__ = [
    "ComparisonOutputsResult",
    "DEFAULT_MESA_BASE_SEED",
    "LoadedBehaviorSpaceTable",
    "MesaValidationOutput",
    "MesaValidationOutputsResult",
    "SeedManifestEntry",
    "ShapeCheckSummary",
    "ShapeComparisonSummary",
    "SmokeRunResult",
    "build_seed_manifest",
    "build_argument_parser",
    "compare_table_shapes",
    "derive_mesa_seed",
    "load_mesa_csv",
    "load_netlogo_behavior_space_table",
    "main",
    "summarize_table_shape",
    "write_comparison_outputs",
    "write_mesa_validation_outputs",
    "write_mesa_smoke_output",
]


if __name__ == "__main__":
    raise SystemExit(main())
