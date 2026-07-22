"""Machine-readable Slumulation slum-size result summaries."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from random import Random
from typing import Literal

import numpy as np

from .dynamics import slumulate_step
from .runner import metric_values
from .setup import load_setup_parameters, setup_initial_world
from .validation import load_mesa_csv, load_netlogo_behavior_space_table

Engine = Literal["netlogo", "mesa"]

FINAL_STEP = 50
NETLOGO_SLUM_SIZE_BASE_SEED = 20260711
MINIMUM_SLUM_SIZE = 2
MAXIMUM_EXPLICIT_SLUM_SIZE = 30
OVERFLOW_BIN = "31+"
SLUM_SIZE_BINS = tuple(
    str(value) for value in range(MINIMUM_SLUM_SIZE, MAXIMUM_EXPLICIT_SLUM_SIZE + 1)
) + (OVERFLOW_BIN,)

DEFAULT_NETLOGO_PATCH_SIZES = Path(
    "results/slumulation/netlogo/slum_size_patch_sizes.csv"
)
DEFAULT_MESA_PATCH_SIZES = Path("results/slumulation/mesa/slum_size_patch_sizes.csv")


@dataclass(frozen=True, slots=True)
class SlumPatchSize:
    """One slum-patch occupancy observation at the final simulation step."""

    engine: Engine
    run_number: int
    seed: int
    patch_index: int
    slum_occupants: int


@dataclass(frozen=True, slots=True)
class SlumSizeExtraction:
    """Final-step slum-patch values and their run seeds."""

    engine: Engine
    run_numbers: tuple[int, ...]
    seed_by_run: tuple[tuple[int, int], ...]
    patches: tuple[SlumPatchSize, ...]


@dataclass(frozen=True, slots=True)
class SlumSizeSummaryOutputs:
    """CSV paths produced from final-step slum-patch values."""

    output_dir: Path
    distribution_by_run_path: Path
    distribution_path: Path


def load_mesa_seed_manifest(
    path: str | Path,
    *,
    experiment_name: str = "Typical Run",
) -> tuple[dict[str, object], ...]:
    """Load a Mesa seed manifest for one experiment."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError("Mesa seed manifest must contain a non-empty entries list.")

    normalized: list[dict[str, object]] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, Mapping):
            raise ValueError("Mesa seed manifest contains a non-object entry.")
        entry = dict(raw_entry)
        if entry.get("experiment_name") != experiment_name:
            raise ValueError(
                f"Mesa seed manifest contains an experiment other than {experiment_name!r}."
            )
        for name in ("run_number", "repetition_index", "seed"):
            if isinstance(entry.get(name), bool) or not isinstance(
                entry.get(name), int
            ):
                raise ValueError(f"Mesa seed manifest entry has invalid {name!r}.")
        if not isinstance(entry.get("parameter_values"), list):
            raise ValueError("Mesa seed manifest entry is missing parameter_values.")
        normalized.append(entry)

    normalized.sort(key=lambda entry: int(entry["run_number"]))
    run_numbers = [int(entry["run_number"]) for entry in normalized]
    if run_numbers != list(range(1, len(normalized) + 1)):
        raise ValueError("Mesa seed manifest run numbers must be consecutive from 1.")
    seeds = [int(entry["seed"]) for entry in normalized]
    if len(set(seeds)) != len(seeds):
        raise ValueError("Mesa seed manifest must contain distinct seeds.")
    return tuple(normalized)


def parse_netlogo_slum_size_final_state(
    path: str | Path,
    *,
    expected_repetitions: int = 30,
    final_step: int = FINAL_STEP,
) -> SlumSizeExtraction:
    """Parse final-step slum-patch occupancies from a NetLogo table."""

    if expected_repetitions < 1:
        raise ValueError("expected_repetitions must be positive.")
    table = load_netlogo_behavior_space_table(path)
    patch_reporter = "sort [slum-occupants] of patches with [slum? = true]"
    required = {"[run number]", "[step]", "behaviorspace-run-number", patch_reporter}
    missing = sorted(required.difference(table.columns))
    if missing:
        raise ValueError(f"NetLogo slum-size table is missing columns: {missing!r}.")

    by_run: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in table.rows:
        by_run[_strict_int(row["[run number]"], "[run number]")].append(row)
    expected_runs = tuple(range(1, expected_repetitions + 1))
    if tuple(sorted(by_run)) != expected_runs:
        raise ValueError("NetLogo slum-size table does not contain the expected runs.")

    seed_by_run: list[tuple[int, int]] = []
    patches: list[SlumPatchSize] = []
    for run_number in expected_runs:
        final_rows = [
            row
            for row in by_run[run_number]
            if _strict_int(row["[step]"], "[step]") == final_step
        ]
        if len(final_rows) != 1:
            raise ValueError(
                f"NetLogo run {run_number} lacks one step-{final_step} row."
            )
        final_row = final_rows[0]
        behavior_space_run = _strict_int(
            final_row["behaviorspace-run-number"], "behaviorspace-run-number"
        )
        if behavior_space_run != run_number:
            raise ValueError(
                "NetLogo BehaviorSpace run number does not match table run number."
            )
        seed = NETLOGO_SLUM_SIZE_BASE_SEED + behavior_space_run
        seed_by_run.append((run_number, seed))
        values = _parse_netlogo_integer_list(final_row[patch_reporter])
        for patch_index, value in enumerate(values, start=1):
            _validate_slum_size(value)
            patches.append(
                SlumPatchSize("netlogo", run_number, seed, patch_index, value)
            )

    return SlumSizeExtraction(
        engine="netlogo",
        run_numbers=expected_runs,
        seed_by_run=tuple(seed_by_run),
        patches=tuple(patches),
    )


def extract_mesa_slum_size_final_state(
    *,
    manifest_path: str | Path,
    mesa_raw_path: str | Path,
    final_step: int = FINAL_STEP,
) -> SlumSizeExtraction:
    """Rerun recorded Mesa seeds and extract final-step slum-patch occupancies."""

    entries = load_mesa_seed_manifest(manifest_path)
    table = load_mesa_csv(mesa_raw_path)
    raw_final_rows = {
        (
            _strict_int(row["[run number]"], "[run number]"),
            _strict_int(row["[step]"], "[step]"),
        ): row
        for row in table.rows
    }

    patches: list[SlumPatchSize] = []
    seed_by_run: list[tuple[int, int]] = []
    for entry in entries:
        run_number = int(entry["run_number"])
        seed = int(entry["seed"])
        setup = setup_initial_world(
            parameter_values=_manifest_parameter_mapping(entry),
            seed=seed,
        )
        parameters = load_setup_parameters(setup.parameters)
        world = setup.world
        rng = Random(seed)
        for step in range(1, final_step + 1):
            result = slumulate_step(world, parameters, rng)
            if result.stopped or not result.tick_advanced:
                raise RuntimeError(
                    f"Mesa run {run_number} stopped before source step {final_step}."
                )
            if step != world.time:
                raise RuntimeError(
                    f"Mesa run {run_number} time drifted from step {step}."
                )

        reference = raw_final_rows.get((run_number, final_step))
        if reference is None:
            raise ValueError(
                f"Mesa raw table lacks run {run_number} step {final_step}."
            )
        _validate_mesa_final_metrics(world, reference)
        seed_by_run.append((run_number, seed))
        slum_patches = sorted(
            (patch for patch in world.patches.values() if patch.slum),
            key=lambda patch: (patch.y, patch.x),
        )
        for patch_index, patch in enumerate(slum_patches, start=1):
            _validate_slum_size(patch.slum_occupants)
            patches.append(
                SlumPatchSize(
                    "mesa", run_number, seed, patch_index, patch.slum_occupants
                )
            )

    return SlumSizeExtraction(
        engine="mesa",
        run_numbers=tuple(int(entry["run_number"]) for entry in entries),
        seed_by_run=tuple(seed_by_run),
        patches=tuple(patches),
    )


def load_slum_patch_sizes(
    path: str | Path,
    *,
    expected_engine: Engine,
) -> SlumSizeExtraction:
    """Load a machine-readable final-step slum-patch CSV."""

    with Path(path).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"Slum-patch CSV is empty: {path}.")

    patches: list[SlumPatchSize] = []
    seed_by_run: dict[int, int] = {}
    for row in rows:
        engine = row.get("engine")
        if engine != expected_engine:
            raise ValueError(f"Expected {expected_engine!r} rows, found {engine!r}.")
        patch = SlumPatchSize(
            expected_engine,
            _strict_int(row.get("run_number"), "run_number"),
            _strict_int(row.get("seed"), "seed"),
            _strict_int(row.get("patch_index"), "patch_index"),
            _strict_int(row.get("slum_occupants"), "slum_occupants"),
        )
        _validate_slum_size(patch.slum_occupants)
        previous_seed = seed_by_run.setdefault(patch.run_number, patch.seed)
        if previous_seed != patch.seed:
            raise ValueError("A run has multiple seeds in the slum-patch CSV.")
        patches.append(patch)

    run_numbers = tuple(sorted(seed_by_run))
    if run_numbers != tuple(range(1, len(run_numbers) + 1)):
        raise ValueError("Slum-patch run numbers must be consecutive from 1.")
    return SlumSizeExtraction(
        engine=expected_engine,
        run_numbers=run_numbers,
        seed_by_run=tuple((run, seed_by_run[run]) for run in run_numbers),
        patches=tuple(patches),
    )


def write_slum_patch_sizes(path: str | Path, extraction: SlumSizeExtraction) -> Path:
    """Write final-step slum-patch values as CSV."""

    target = Path(path)
    _write_csv(
        target,
        ("engine", "run_number", "seed", "patch_index", "slum_occupants"),
        [asdict(patch) for patch in extraction.patches],
    )
    return target


def aggregate_slum_size_distribution(
    extraction: SlumSizeExtraction,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return run-normalized and equal-run-weighted slum-size distributions."""

    values_by_run: dict[int, list[int]] = {run: [] for run in extraction.run_numbers}
    seeds = dict(extraction.seed_by_run)
    for patch in extraction.patches:
        if patch.run_number not in values_by_run:
            raise ValueError("Slum-patch value references an unknown run.")
        if seeds.get(patch.run_number) != patch.seed:
            raise ValueError("Slum-patch seed does not match its run manifest.")
        _validate_slum_size(patch.slum_occupants)
        values_by_run[patch.run_number].append(patch.slum_occupants)

    run_rows: list[dict[str, object]] = []
    probability_by_bin: dict[str, list[float]] = {label: [] for label in SLUM_SIZE_BINS}
    for run_number in extraction.run_numbers:
        values = values_by_run[run_number]
        if not values:
            raise ValueError(f"Slum-size run {run_number} has no slum patches.")
        counts = {label: 0 for label in SLUM_SIZE_BINS}
        for value in values:
            counts[_slum_size_bin(value)] += 1
        denominator = len(values)
        for label in SLUM_SIZE_BINS:
            probability = counts[label] / denominator
            probability_by_bin[label].append(probability)
            run_rows.append(
                {
                    "engine": extraction.engine,
                    "run_number": run_number,
                    "seed": seeds[run_number],
                    "bin": label,
                    "patch_count": counts[label],
                    "run_patch_total": denominator,
                    "probability": probability,
                }
            )

    summary_rows = [
        {
            "engine": extraction.engine,
            "bin": label,
            "run_count": len(extraction.run_numbers),
            "mean_probability": float(np.mean(probability_by_bin[label])),
        }
        for label in SLUM_SIZE_BINS
    ]
    return run_rows, summary_rows


def write_slum_size_summaries(
    output_dir: str | Path,
    *,
    netlogo_patch_sizes: str | Path = DEFAULT_NETLOGO_PATCH_SIZES,
    mesa_patch_sizes: str | Path = DEFAULT_MESA_PATCH_SIZES,
) -> SlumSizeSummaryOutputs:
    """Generate distribution CSVs from included final-step patch values."""

    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Output directory already exists: {destination}.")
    destination.mkdir(parents=True, exist_ok=False)

    netlogo = load_slum_patch_sizes(
        netlogo_patch_sizes,
        expected_engine="netlogo",
    )
    mesa = load_slum_patch_sizes(mesa_patch_sizes, expected_engine="mesa")
    netlogo_run_rows, netlogo_summary_rows = aggregate_slum_size_distribution(netlogo)
    mesa_run_rows, mesa_summary_rows = aggregate_slum_size_distribution(mesa)

    distribution_by_run_path = destination / "distribution_by_run.csv"
    distribution_path = destination / "distribution.csv"
    _write_csv(
        distribution_by_run_path,
        (
            "engine",
            "run_number",
            "seed",
            "bin",
            "patch_count",
            "run_patch_total",
            "probability",
        ),
        [*netlogo_run_rows, *mesa_run_rows],
    )
    _write_csv(
        distribution_path,
        ("engine", "bin", "run_count", "mean_probability"),
        [*netlogo_summary_rows, *mesa_summary_rows],
    )
    return SlumSizeSummaryOutputs(
        output_dir=destination,
        distribution_by_run_path=distribution_by_run_path,
        distribution_path=distribution_path,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the slum-size summary command parser."""

    parser = argparse.ArgumentParser(
        description="Generate Slumulation slum-size distribution CSV summaries."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New directory that will receive the generated CSVs.",
    )
    parser.add_argument(
        "--netlogo-patch-sizes",
        type=Path,
        default=DEFAULT_NETLOGO_PATCH_SIZES,
        help="NetLogo final-step slum-patch CSV.",
    )
    parser.add_argument(
        "--mesa-patch-sizes",
        type=Path,
        default=DEFAULT_MESA_PATCH_SIZES,
        help="Mesa final-step slum-patch CSV.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Generate slum-size distribution summaries."""

    arguments = build_argument_parser().parse_args(argv)
    result = write_slum_size_summaries(
        arguments.output_dir,
        netlogo_patch_sizes=arguments.netlogo_patch_sizes,
        mesa_patch_sizes=arguments.mesa_patch_sizes,
    )
    print(result.distribution_by_run_path)
    print(result.distribution_path)
    return 0


def _manifest_parameter_mapping(entry: Mapping[str, object]) -> dict[str, object]:
    values = entry.get("parameter_values")
    if not isinstance(values, list):
        raise ValueError("Manifest entry has no parameter_values list.")
    mapping: dict[str, object] = {}
    for item in values:
        if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str):
            raise ValueError("Manifest entry has an invalid parameter value.")
        mapping[item[0]] = item[1]
    return mapping


def _validate_mesa_final_metrics(world: object, reference: Mapping[str, str]) -> None:
    values = metric_values(world)  # type: ignore[arg-type]
    for metric, value in values.items():
        try:
            expected = float(reference[metric])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid Mesa raw reference metric {metric!r}.") from exc
        if not math.isclose(float(value), expected, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(
                f"Mesa final-state metric {metric!r} differs from its raw row."
            )


def _parse_netlogo_integer_list(raw: str) -> tuple[int, ...]:
    text = raw.strip()
    if text == "[]":
        return ()
    if not text.startswith("[") or not text.endswith("]"):
        raise ValueError("NetLogo slum-patch reporter is not a list literal.")
    body = text[1:-1].strip()
    if not body:
        return ()
    return tuple(_strict_int(token, "slum-occupants") for token in body.split())


def _validate_slum_size(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Slum-patch sizes must be integers.")
    if value < MINIMUM_SLUM_SIZE:
        raise ValueError(f"Slum-patch size must be at least {MINIMUM_SLUM_SIZE}.")


def _slum_size_bin(value: int) -> str:
    _validate_slum_size(value)
    if value <= MAXIMUM_EXPLICIT_SLUM_SIZE:
        return str(value)
    return OVERFLOW_BIN


def _strict_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer.")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer.") from exc
    if not number.is_integer():
        raise ValueError(f"{label} must be an integer.")
    return int(number)


def _write_csv(
    path: Path,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


__all__ = [
    "DEFAULT_MESA_PATCH_SIZES",
    "DEFAULT_NETLOGO_PATCH_SIZES",
    "FINAL_STEP",
    "MAXIMUM_EXPLICIT_SLUM_SIZE",
    "MINIMUM_SLUM_SIZE",
    "NETLOGO_SLUM_SIZE_BASE_SEED",
    "OVERFLOW_BIN",
    "SLUM_SIZE_BINS",
    "SlumPatchSize",
    "SlumSizeExtraction",
    "SlumSizeSummaryOutputs",
    "aggregate_slum_size_distribution",
    "build_argument_parser",
    "extract_mesa_slum_size_final_state",
    "load_mesa_seed_manifest",
    "load_slum_patch_sizes",
    "main",
    "parse_netlogo_slum_size_final_state",
    "write_slum_patch_sizes",
    "write_slum_size_summaries",
]


if __name__ == "__main__":
    raise SystemExit(main())
