from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from .model import (
    JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
    MOVEMENT_ORDER_ALL_RANDOM,
    SakodaModel,
)
from .scenarios import (
    CROSSES,
    DEFAULT_COLUMNS,
    DEFAULT_DISTANCE_WEIGHT,
    DEFAULT_GROUP_SIZE,
    DEFAULT_ROWS,
    DEFAULT_SEEDS,
    SCENARIO_LIST,
    SQUARES,
    ScenarioConfig,
    get_scenario,
)


def run_validation_suite(
    *,
    output_dir: Path | str,
    scenario_names: Iterable[str] | None = None,
    seeds: Iterable[int] = DEFAULT_SEEDS,
    jump_rule: str = JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
    movement_order: str = MOVEMENT_ORDER_ALL_RANDOM,
) -> dict[str, Any]:
    """Run Sakoda scenarios and write machine-readable result data."""

    output_dir = Path(output_dir)
    runs_dir = output_dir / "runs"
    summaries_dir = output_dir / "summaries"
    runs_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)

    scenarios = _select_scenarios(scenario_names)
    seed_values = tuple(seeds)
    summary_rows: list[dict[str, Any]] = []

    for scenario in scenarios:
        for seed in seed_values:
            model = SakodaModel(
                scenario,
                seed=seed,
                rows=DEFAULT_ROWS,
                columns=DEFAULT_COLUMNS,
                group_size=DEFAULT_GROUP_SIZE,
                distance_weight=DEFAULT_DISTANCE_WEIGHT,
                max_cycles=scenario.max_cycles,
                jump_rule=jump_rule,
                movement_order=movement_order,
            ).run()
            record = model.to_run_record()

            run_stem = f"{scenario.name}_seed_{seed}"
            _write_json(runs_dir / f"{run_stem}.json", record)
            _write_cycle_metrics_csv(
                runs_dir / f"{run_stem}_metrics.csv",
                record["metrics_by_cycle"],
            )
            summary_rows.append(_summary_row(record))

    _write_table(summaries_dir / "runs.csv", summary_rows)

    return {
        "output_dir": str(output_dir),
        "run_count": len(summary_rows),
        "summary_rows": summary_rows,
    }


def write_validation_suite(
    output_dir: Path | str,
    *,
    scenario_names: Iterable[str] | None = None,
    seeds: Iterable[int] = DEFAULT_SEEDS,
) -> dict[str, Any]:
    """Write Sakoda run and summary data to a new output directory."""

    destination = _create_new_output_directory(output_dir)
    return run_validation_suite(
        output_dir=destination,
        scenario_names=scenario_names,
        seeds=seeds,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the Sakoda result-generation command parser."""

    parser = argparse.ArgumentParser(
        description="Run Sakoda checkerboard scenarios and write result data.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        help="Scenario name to run. Repeat to select multiple scenarios. Defaults to all.",
    )
    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=list(DEFAULT_SEEDS),
        help="Reproducible random seeds.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New directory for generated run and summary data.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Sakoda result-generation command."""

    args = build_argument_parser().parse_args(argv)
    result = write_validation_suite(
        args.output_dir,
        scenario_names=args.scenarios,
        seeds=args.seeds,
    )
    print(f"Wrote {result['run_count']} Sakoda runs to {result['output_dir']}")
    return 0


def _create_new_output_directory(path: Path | str) -> Path:
    destination = Path(path).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Output directory already exists: {destination}.")
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def _select_scenarios(
    scenario_names: Iterable[str] | None,
) -> tuple[ScenarioConfig, ...]:
    if scenario_names is None:
        return SCENARIO_LIST
    return tuple(get_scenario(name) for name in scenario_names)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_cycle_metrics_csv(
    path: Path, metrics_by_cycle: list[dict[str, Any]]
) -> None:
    _write_table(path, metrics_by_cycle)


def _write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _summary_row(record: dict[str, Any]) -> dict[str, Any]:
    cycle_metrics = [
        metric for metric in record["metrics_by_cycle"] if metric["cycle"] > 0
    ]
    recent_metrics = cycle_metrics[-10:]
    final_metrics = record["metrics_by_cycle"][-1]
    return {
        "scenario": record["scenario"],
        "display_name": record["display_name"],
        "source_caption": record["source_caption"],
        "seed": record["seed"],
        "max_cycles": record["max_cycles"],
        "cycles_completed": record["cycles_completed"],
        "stop_reason": record["stop_reason"],
        "squares_own": record["attitudes"][SQUARES]["own_group"],
        "squares_other": record["attitudes"][SQUARES]["other_group"],
        "crosses_own": record["attitudes"][CROSSES]["own_group"],
        "crosses_other": record["attitudes"][CROSSES]["other_group"],
        "final_movement_count": final_metrics["movement_count"],
        "total_movement_count": sum(
            metric["movement_count"] for metric in cycle_metrics
        ),
        "stable_cycle_count": sum(1 for metric in cycle_metrics if metric["stable"]),
        "final_cycle_stable": final_metrics["stable"],
        "recent_moving_cycles": sum(
            1 for metric in recent_metrics if metric["movement_count"] > 0
        ),
        "final_centroid_distance": final_metrics["centroid_distance"],
        "final_squares_dispersion": final_metrics["squares_dispersion"],
        "final_crosses_dispersion": final_metrics["crosses_dispersion"],
        "final_same_group_adjacent_pairs": final_metrics["same_group_adjacent_pairs"],
        "final_mixed_adjacent_pairs": final_metrics["mixed_adjacent_pairs"],
        "final_squares_edge_count": final_metrics["squares_edge_count"],
        "final_crosses_edge_count": final_metrics["crosses_edge_count"],
        "final_squares_corner_count": final_metrics["squares_corner_count"],
        "final_crosses_corner_count": final_metrics["crosses_corner_count"],
        "final_squares_mean_center_distance": final_metrics[
            "squares_mean_center_distance"
        ],
        "final_crosses_mean_center_distance": final_metrics[
            "crosses_mean_center_distance"
        ],
        "final_checkerboard_alignment": final_metrics["checkerboard_alignment"],
        "final_mixed_nearest_neighbor_count": final_metrics[
            "mixed_nearest_neighbor_count"
        ],
        "final_mean_nearest_same_distance": final_metrics["mean_nearest_same_distance"],
        "final_mean_nearest_other_distance": final_metrics[
            "mean_nearest_other_distance"
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
