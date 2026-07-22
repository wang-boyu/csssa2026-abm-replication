from __future__ import annotations

import argparse
import csv
import json
import os
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from statistics import mean, stdev

from .model import YaTASERPSModel


PAPER_PARAMETER_ORDER: tuple[tuple[str, str], ...] = (
    ("promotive-level", "promotive_level"),
    ("risk-level", "risk_level"),
    ("schools-promotive", "schools_promotive"),
    ("schools-risk", "schools_risk"),
    ("neighborhood-promotive", "neighborhood_promotive"),
    ("neighborhood-risk", "neighborhood_risk"),
)
PAPER_PARAMETER_LEVELS: tuple[int, int, int] = (25, 50, 75)
DEFAULT_SEED_SET: tuple[int, ...] = tuple(range(1, 11))

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPOSITORY_ROOT / "results" / "yatasterps"
INCLUDED_RUNS_DIR = RESULTS_DIR / "runs"
INCLUDED_SUMMARIES_DIR = RESULTS_DIR / "summaries"
INCLUDED_MESA_RAW_RUNS_PATH = INCLUDED_RUNS_DIR / "mesa_raw_runs.csv"
INCLUDED_NETLOGO_RAW_RUNS_PATH = INCLUDED_RUNS_DIR / "netlogo_raw_runs.csv"

NETLOGO_PARAMETER_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("promotive-level", "promotive_level"),
    ("risk-level", "risk_level"),
    ("schools-promotive", "schools_promotive"),
    ("schools-risk", "schools_risk"),
    ("neighborhood-promotive", "neighborhood_promotive"),
    ("neighborhood-risk", "neighborhood_risk"),
)
NETLOGO_FINAL_VALUE_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("[step]", "total_steps"),
    (
        "count turtles with [antisocial > prosocial] / count turtles",
        "percent_antisocial",
    ),
    ("mean [prosocial] of turtles", "prosocial_experience_score"),
    ("mean [antisocial] of turtles", "antisocial_experience_score"),
    ("mean [family-risk] of turtles", "family_risk_mean"),
    ("mean [family-pro] of turtles", "family_promotive_mean"),
    ("mean [risk-opp] of school-patches", "school_risk_mean"),
    ("mean [pro-opp] of school-patches", "school_promotive_mean"),
    ("mean [risk-opp] of neighborhood-patches", "neighborhood_risk_mean"),
    ("mean [pro-opp] of neighborhood-patches", "neighborhood_promotive_mean"),
)
NETLOGO_BLOCK_SIZE = 38

RAW_RUN_FIELDNAMES: tuple[str, ...] = (
    "bundle_id",
    "seed",
    "promotive_level",
    "risk_level",
    "schools_promotive",
    "schools_risk",
    "neighborhood_promotive",
    "neighborhood_risk",
    "antisocial_experience_score",
    "prosocial_experience_score",
    "percent_antisocial",
    "family_risk_mean",
    "family_promotive_mean",
    "school_risk_mean",
    "school_promotive_mean",
    "neighborhood_risk_mean",
    "neighborhood_promotive_mean",
)
NETLOGO_RAW_RUN_FIELDNAMES: tuple[str, ...] = (
    "bundle_id",
    "run_number",
    "repetition",
    "promotive_level",
    "risk_level",
    "schools_promotive",
    "schools_risk",
    "neighborhood_promotive",
    "neighborhood_risk",
    "total_steps",
    "antisocial_experience_score",
    "prosocial_experience_score",
    "percent_antisocial",
    "family_risk_mean",
    "family_promotive_mean",
    "school_risk_mean",
    "school_promotive_mean",
    "neighborhood_risk_mean",
    "neighborhood_promotive_mean",
)

INPUT_LEVELS: tuple[int, int, int] = (25, 50, 75)
PROSOCIAL_OUTCOME_FIELD = "prosocial_experience_score"
PROSOCIAL_INPUTS: tuple[dict[str, str | bool], ...] = (
    {
        "field": "promotive_level",
        "label": "Family Promotive",
        "paper_significant": True,
        "paper_direction": "increasing",
        "paper_f": "2092.87",
        "paper_p": "<.001",
    },
    {
        "field": "risk_level",
        "label": "Family Risk",
        "paper_significant": True,
        "paper_direction": "decreasing",
        "paper_f": "650.38",
        "paper_p": "<.001",
    },
    {
        "field": "schools_promotive",
        "label": "School Promotive",
        "paper_significant": True,
        "paper_direction": "increasing",
        "paper_f": "1222.53",
        "paper_p": "<.001",
    },
    {
        "field": "schools_risk",
        "label": "School Risk",
        "paper_significant": False,
        "paper_direction": "",
        "paper_f": "0.05",
        "paper_p": ".9552",
    },
    {
        "field": "neighborhood_promotive",
        "label": "Neighborhood Promotive",
        "paper_significant": True,
        "paper_direction": "increasing",
        "paper_f": "379.10",
        "paper_p": "<.001",
    },
    {
        "field": "neighborhood_risk",
        "label": "Neighborhood Risk",
        "paper_significant": False,
        "paper_direction": "",
        "paper_f": "0.35",
        "paper_p": ".7034",
    },
)
ANTISOCIAL_OUTCOME_FIELD = "antisocial_experience_score"
ANTISOCIAL_INPUTS: tuple[dict[str, str | bool], ...] = (
    {
        "field": "promotive_level",
        "label": "Family Promotive",
        "paper_significant": True,
        "paper_direction": "decreasing",
        "paper_f": "446.90",
        "paper_p": "<.001",
    },
    {
        "field": "risk_level",
        "label": "Family Risk",
        "paper_significant": True,
        "paper_direction": "increasing",
        "paper_f": "1376.31",
        "paper_p": "<.001",
    },
    {
        "field": "schools_promotive",
        "label": "School Promotive",
        "paper_significant": True,
        "paper_direction": "decreasing",
        "paper_f": "20.58",
        "paper_p": "<.001",
    },
    {
        "field": "schools_risk",
        "label": "School Risk",
        "paper_significant": True,
        "paper_direction": "increasing",
        "paper_f": "610.41",
        "paper_p": "<.001",
    },
    {
        "field": "neighborhood_promotive",
        "label": "Neighborhood Promotive",
        "paper_significant": True,
        "paper_direction": "decreasing",
        "paper_f": "199.25",
        "paper_p": "<.001",
    },
    {
        "field": "neighborhood_risk",
        "label": "Neighborhood Risk",
        "paper_significant": True,
        "paper_direction": "increasing",
        "paper_f": "1646.85",
        "paper_p": "<.001",
    },
)
SUMMARY_FIELDNAMES: tuple[str, ...] = (
    "source_key",
    "source_label",
    "input_field",
    "input_label",
    "paper_significant",
    "paper_direction",
    "paper_f",
    "paper_p",
    "level_25_n",
    "level_25_mean",
    "level_25_std",
    "level_50_n",
    "level_50_mean",
    "level_50_std",
    "level_75_n",
    "level_75_mean",
    "level_75_std",
    "anova_f",
    "anova_p",
    "significant",
    "observed_direction",
    "significance_match",
    "direction_match",
    "overall_match",
)


@dataclass(frozen=True)
class ParameterBundle:
    bundle_id: int
    promotive_level: int
    risk_level: int
    schools_promotive: int
    schools_risk: int
    neighborhood_promotive: int
    neighborhood_risk: int

    def manifest_row(self) -> dict[str, int]:
        return {
            "bundle_id": self.bundle_id,
            "paper_promotive-level": self.promotive_level,
            "mesa_promotive_level": self.promotive_level,
            "paper_risk-level": self.risk_level,
            "mesa_risk_level": self.risk_level,
            "paper_schools-promotive": self.schools_promotive,
            "mesa_schools_promotive": self.schools_promotive,
            "paper_schools-risk": self.schools_risk,
            "mesa_schools_risk": self.schools_risk,
            "paper_neighborhood-promotive": self.neighborhood_promotive,
            "mesa_neighborhood_promotive": self.neighborhood_promotive,
            "paper_neighborhood-risk": self.neighborhood_risk,
            "mesa_neighborhood_risk": self.neighborhood_risk,
        }

    def model_kwargs(self) -> dict[str, int]:
        return {
            "promotive_level": self.promotive_level,
            "risk_level": self.risk_level,
            "schools_promotive": self.schools_promotive,
            "schools_risk": self.schools_risk,
            "neighborhood_promotive": self.neighborhood_promotive,
            "neighborhood_risk": self.neighborhood_risk,
        }


def generate_parameter_manifest(
    levels: Iterable[int] = PAPER_PARAMETER_LEVELS,
) -> list[ParameterBundle]:
    bundles: list[ParameterBundle] = []
    for bundle_id, values in enumerate(
        product(levels, repeat=len(PAPER_PARAMETER_ORDER)), start=1
    ):
        bundles.append(
            ParameterBundle(
                bundle_id=bundle_id,
                **dict(
                    zip(
                        (mesa_name for _, mesa_name in PAPER_PARAMETER_ORDER),
                        values,
                        strict=True,
                    )
                ),
            )
        )
    return bundles


def write_parameter_manifest(path: Path, bundles: Iterable[ParameterBundle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(next(iter(generate_parameter_manifest())).manifest_row().keys())
    rows = [bundle.manifest_row() for bundle in bundles]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_parameter_bundle(
    bundle: ParameterBundle, seeds: Iterable[int], max_ticks: int
) -> list[dict[str, float | int]]:
    rows: list[dict[str, float | int]] = []
    for seed in seeds:
        model = YaTASERPSModel(
            **bundle.model_kwargs(),
            seed=seed,
            max_ticks=max_ticks,
            collect_time_series=False,
            record_pipeline_trace=False,
            refresh_visuals=False,
        )
        while model.running:
            model.step()
        rows.append(
            {
                "bundle_id": bundle.bundle_id,
                "seed": seed,
                **bundle.model_kwargs(),
                "antisocial_experience_score": round(model.mean_antisocial, 12),
                "prosocial_experience_score": round(model.mean_prosocial, 12),
                "percent_antisocial": round(model.percent_antisocial_share, 12),
                "family_risk_mean": round(model.mean_family_risk, 12),
                "family_promotive_mean": round(model.mean_family_pro, 12),
                "school_risk_mean": round(model.mean_school_risk_opp, 12),
                "school_promotive_mean": round(model.mean_school_pro_opp, 12),
                "neighborhood_risk_mean": round(model.mean_neighborhood_risk_opp, 12),
                "neighborhood_promotive_mean": round(
                    model.mean_neighborhood_pro_opp, 12
                ),
            }
        )
    return rows


def _run_parameter_bundle_task(
    task: tuple[ParameterBundle, tuple[int, ...], int],
) -> list[dict[str, float | int]]:
    bundle, seeds, max_ticks = task
    return run_parameter_bundle(bundle, seeds, max_ticks)


def parse_netlogo_runs(source_path: Path) -> list[dict[str, float | int]]:
    with source_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    if len(rows) < 17:
        raise ValueError(
            f"Expected a BehaviorSpace spreadsheet with at least 17 rows, found {len(rows)}."
        )

    run_number_row = rows[6]
    final_value_labels_row = rows[15]
    final_value_data_row = rows[16]
    final_value_labels = final_value_labels_row[1 : NETLOGO_BLOCK_SIZE + 1]
    if len(final_value_labels) != NETLOGO_BLOCK_SIZE:
        raise ValueError(
            "NetLogo export did not contain the expected 38-metric final-value block."
        )
    if len(final_value_data_row) - 1 != len(run_number_row) - 1:
        raise ValueError(
            "NetLogo final-value row width does not match the run-number row."
        )

    parameter_rows = {row[0]: row for row in rows[7:13]}
    bundle_lookup = {
        (
            bundle.promotive_level,
            bundle.risk_level,
            bundle.schools_promotive,
            bundle.schools_risk,
            bundle.neighborhood_promotive,
            bundle.neighborhood_risk,
        ): bundle.bundle_id
        for bundle in generate_parameter_manifest()
    }
    repetition_counts: dict[int, int] = {}
    parsed_rows: list[dict[str, float | int]] = []

    run_count = (len(final_value_data_row) - 1) // NETLOGO_BLOCK_SIZE
    for run_index in range(run_count):
        block_start = 1 + (run_index * NETLOGO_BLOCK_SIZE)
        block_end = block_start + NETLOGO_BLOCK_SIZE
        run_metrics = dict(
            zip(
                final_value_labels,
                final_value_data_row[block_start:block_end],
                strict=True,
            )
        )
        parameter_values = {
            mesa_name: int(parameter_rows[paper_name][block_start])
            for paper_name, mesa_name in NETLOGO_PARAMETER_FIELD_MAP
        }
        bundle_key = (
            int(parameter_values["promotive_level"]),
            int(parameter_values["risk_level"]),
            int(parameter_values["schools_promotive"]),
            int(parameter_values["schools_risk"]),
            int(parameter_values["neighborhood_promotive"]),
            int(parameter_values["neighborhood_risk"]),
        )
        bundle_id = bundle_lookup[bundle_key]
        repetition = repetition_counts.get(bundle_id, 0) + 1
        repetition_counts[bundle_id] = repetition

        parsed_row: dict[str, float | int] = {
            "bundle_id": bundle_id,
            "run_number": int(run_number_row[block_start]),
            "repetition": repetition,
            **parameter_values,
        }
        for netlogo_name, field_name in NETLOGO_FINAL_VALUE_FIELD_MAP:
            value = run_metrics[netlogo_name]
            if field_name == "total_steps":
                parsed_row[field_name] = int(float(value))
            else:
                parsed_row[field_name] = round(float(value), 12)
        parsed_rows.append(parsed_row)

    parsed_rows.sort(key=lambda row: (int(row["bundle_id"]), int(row["repetition"])))
    return parsed_rows


def read_run_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _input_direction(means_by_level: dict[int, float]) -> str:
    ordered_means = [means_by_level[level] for level in INPUT_LEVELS]
    if ordered_means[0] < ordered_means[1] < ordered_means[2]:
        return "increasing"
    if ordered_means[0] > ordered_means[1] > ordered_means[2]:
        return "decreasing"
    return "mixed"


def summarize_outcome(
    rows: list[dict[str, str]],
    *,
    source_key: str,
    source_label: str,
    inputs: tuple[dict[str, str | bool], ...],
    outcome_field: str,
) -> list[dict[str, float | str]]:
    from scipy.stats import f_oneway

    summary_rows: list[dict[str, float | str]] = []
    for spec in inputs:
        input_field = str(spec["field"])
        groups = {
            level: [
                float(row[outcome_field])
                for row in rows
                if int(row[input_field]) == level
            ]
            for level in INPUT_LEVELS
        }
        means_by_level = {level: mean(values) for level, values in groups.items()}
        stds_by_level = {
            level: stdev(values) if len(values) > 1 else 0.0
            for level, values in groups.items()
        }
        anova_result = f_oneway(*(groups[level] for level in INPUT_LEVELS))
        significant = bool(anova_result.pvalue < 0.05)
        paper_significant = bool(spec["paper_significant"])
        paper_direction = str(spec["paper_direction"])
        observed_direction = _input_direction(means_by_level)
        significance_match = significant == paper_significant
        if paper_direction:
            direction_match = observed_direction == paper_direction
            overall_match = significance_match and direction_match
            direction_match_value = str(direction_match).lower()
        else:
            direction_match_value = "not_applicable"
            overall_match = significance_match

        summary_rows.append(
            {
                "source_key": source_key,
                "source_label": source_label,
                "input_field": input_field,
                "input_label": str(spec["label"]),
                "paper_significant": str(paper_significant).lower(),
                "paper_direction": paper_direction,
                "paper_f": str(spec["paper_f"]),
                "paper_p": str(spec["paper_p"]),
                "level_25_n": len(groups[25]),
                "level_25_mean": means_by_level[25],
                "level_25_std": stds_by_level[25],
                "level_50_n": len(groups[50]),
                "level_50_mean": means_by_level[50],
                "level_50_std": stds_by_level[50],
                "level_75_n": len(groups[75]),
                "level_75_mean": means_by_level[75],
                "level_75_std": stds_by_level[75],
                "anova_f": float(anova_result.statistic),
                "anova_p": float(anova_result.pvalue),
                "significant": str(significant).lower(),
                "observed_direction": observed_direction,
                "significance_match": str(significance_match).lower(),
                "direction_match": direction_match_value,
                "overall_match": str(overall_match).lower(),
            }
        )

    return summary_rows


def summarize_prosocial(
    rows: list[dict[str, str]], *, source_key: str, source_label: str
) -> list[dict[str, float | str]]:
    return summarize_outcome(
        rows,
        source_key=source_key,
        source_label=source_label,
        inputs=PROSOCIAL_INPUTS,
        outcome_field=PROSOCIAL_OUTCOME_FIELD,
    )


def summarize_antisocial(
    rows: list[dict[str, str]], *, source_key: str, source_label: str
) -> list[dict[str, float | str]]:
    return summarize_outcome(
        rows,
        source_key=source_key,
        source_label=source_label,
        inputs=ANTISOCIAL_INPUTS,
        outcome_field=ANTISOCIAL_OUTCOME_FIELD,
    )


def write_rows(
    path: Path,
    rows: list[dict[str, float | int | str]],
    fieldnames: tuple[str, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_source_summaries(
    *,
    rows: list[dict[str, str]],
    source_key: str,
    source_label: str,
    output_dir: Path,
) -> tuple[Path, Path]:
    prosocial_path = output_dir / f"prosocial_{source_key}.csv"
    antisocial_path = output_dir / f"antisocial_{source_key}.csv"
    write_rows(
        prosocial_path,
        summarize_prosocial(rows, source_key=source_key, source_label=source_label),
        SUMMARY_FIELDNAMES,
    )
    write_rows(
        antisocial_path,
        summarize_antisocial(rows, source_key=source_key, source_label=source_label),
        SUMMARY_FIELDNAMES,
    )
    return prosocial_path, antisocial_path


def build_summary_artifacts(
    *,
    output_dir: Path,
    mesa_raw_runs_path: Path = INCLUDED_MESA_RAW_RUNS_PATH,
    netlogo_raw_runs_path: Path = INCLUDED_NETLOGO_RAW_RUNS_PATH,
) -> dict[str, object]:
    summaries_dir = output_dir / "summaries"
    mesa_paths = write_source_summaries(
        rows=read_run_rows(mesa_raw_runs_path),
        source_key="mesa",
        source_label="Mesa",
        output_dir=summaries_dir,
    )
    netlogo_paths = write_source_summaries(
        rows=read_run_rows(netlogo_raw_runs_path),
        source_key="netlogo",
        source_label="NetLogo",
        output_dir=summaries_dir,
    )
    return {
        "mesa_raw_runs_path": str(mesa_raw_runs_path.resolve()),
        "netlogo_raw_runs_path": str(netlogo_raw_runs_path.resolve()),
        "summary_paths": [
            str(path.resolve()) for path in (*mesa_paths, *netlogo_paths)
        ],
    }


def build_netlogo_parse_artifacts(
    *, source_path: Path, output_dir: Path
) -> dict[str, object]:
    rows = parse_netlogo_runs(source_path)
    raw_runs_path = output_dir / "runs" / "netlogo_raw_runs.csv"
    write_rows(raw_runs_path, rows, NETLOGO_RAW_RUN_FIELDNAMES)
    summary_paths = write_source_summaries(
        rows=[{key: str(value) for key, value in row.items()} for row in rows],
        source_key="netlogo",
        source_label="NetLogo",
        output_dir=output_dir / "summaries",
    )
    return {
        "source_path": str(source_path.resolve()),
        "run_count": len(rows),
        "raw_runs_path": str(raw_runs_path.resolve()),
        "summary_paths": [str(path.resolve()) for path in summary_paths],
    }


def build_sweep_artifacts(
    *,
    output_dir: Path,
    max_ticks: int = 1800,
    seeds: tuple[int, ...] = DEFAULT_SEED_SET,
    workers: int | None = None,
) -> dict[str, object]:
    bundles = generate_parameter_manifest()
    workers = workers or max(1, (os.cpu_count() or 1) - 1)
    runs_dir = output_dir / "runs"
    summaries_dir = output_dir / "summaries"
    manifest_path = runs_dir / "parameter_manifest.csv"
    write_parameter_manifest(manifest_path, bundles)

    start_time = time.perf_counter()
    rows: list[dict[str, float | int]] = []
    tasks = [(bundle, seeds, max_ticks) for bundle in bundles]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for bundle_rows in executor.map(_run_parameter_bundle_task, tasks, chunksize=1):
            rows.extend(bundle_rows)
    elapsed_seconds = time.perf_counter() - start_time

    rows.sort(key=lambda row: (int(row["bundle_id"]), int(row["seed"])))
    raw_runs_path = runs_dir / "mesa_raw_runs.csv"
    write_rows(raw_runs_path, rows, RAW_RUN_FIELDNAMES)
    summary_paths = write_source_summaries(
        rows=[{key: str(value) for key, value in row.items()} for row in rows],
        source_key="mesa",
        source_label="Mesa",
        output_dir=summaries_dir,
    )
    return {
        "bundle_count": len(bundles),
        "seed_count": len(seeds),
        "run_count": len(rows),
        "max_ticks": max_ticks,
        "workers": workers,
        "elapsed_seconds": elapsed_seconds,
        "manifest_path": str(manifest_path.resolve()),
        "raw_runs_path": str(raw_runs_path.resolve()),
        "summary_paths": [str(path.resolve()) for path in summary_paths],
    }


def _resolve_new_output_directory(path: Path) -> Path:
    output_dir = path.expanduser().resolve()
    if output_dir == RESULTS_DIR or RESULTS_DIR in output_dir.parents:
        raise ValueError(
            f"output directory must be outside included results: {RESULTS_DIR}"
        )
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError(f"output path exists and is not a directory: {output_dir}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"output directory must be new or empty: {output_dir}")
    return output_dir


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Ya-TASERPS run data and machine-readable summaries.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New or empty directory for generated run data and summaries.",
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument(
        "--run-sweep",
        action="store_true",
        help="Run the 729-bundle Mesa experiment and write raw data and summaries.",
    )
    actions.add_argument(
        "--summarize-runs",
        action="store_true",
        help="Regenerate NetLogo and Mesa summaries from raw run CSVs.",
    )
    actions.add_argument(
        "--parse-netlogo-runs",
        action="store_true",
        help="Parse a NetLogo BehaviorSpace export into raw data and summaries.",
    )
    actions.add_argument(
        "--write-manifest-only",
        action="store_true",
        help="Write the parameter manifest without running the model.",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=1800,
        help="Number of model days per Mesa run.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 1) - 1),
        help="Number of worker processes for the Mesa sweep.",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=list(DEFAULT_SEED_SET),
        help="Explicit seed list reused for every parameter bundle.",
    )
    parser.add_argument(
        "--mesa-raw-runs",
        type=Path,
        default=INCLUDED_MESA_RAW_RUNS_PATH,
        help="Mesa raw-run CSV used by --summarize-runs.",
    )
    parser.add_argument(
        "--netlogo-raw-runs",
        type=Path,
        default=INCLUDED_NETLOGO_RAW_RUNS_PATH,
        help="NetLogo raw-run CSV used by --summarize-runs.",
    )
    parser.add_argument(
        "--netlogo-source",
        type=Path,
        help="NetLogo BehaviorSpace spreadsheet used by --parse-netlogo-runs.",
    )
    args = parser.parse_args(argv)
    if args.parse_netlogo_runs and args.netlogo_source is None:
        parser.error("--netlogo-source is required with --parse-netlogo-runs")
    try:
        args.output_dir = _resolve_new_output_directory(args.output_dir)
    except ValueError as error:
        parser.error(str(error))
    return args


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.write_manifest_only:
        bundles = generate_parameter_manifest()
        manifest_path = output_dir / "runs" / "parameter_manifest.csv"
        write_parameter_manifest(manifest_path, bundles)
        result: dict[str, object] = {
            "manifest_path": str(manifest_path.resolve()),
            "bundle_count": len(bundles),
        }
    elif args.summarize_runs:
        result = build_summary_artifacts(
            output_dir=output_dir,
            mesa_raw_runs_path=args.mesa_raw_runs,
            netlogo_raw_runs_path=args.netlogo_raw_runs,
        )
    elif args.parse_netlogo_runs:
        result = build_netlogo_parse_artifacts(
            source_path=args.netlogo_source,
            output_dir=output_dir,
        )
    elif args.run_sweep:
        result = build_sweep_artifacts(
            output_dir=output_dir,
            max_ticks=args.max_ticks,
            seeds=tuple(args.seeds),
            workers=args.workers,
        )
    else:
        raise AssertionError("argparse accepted no replication action")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
