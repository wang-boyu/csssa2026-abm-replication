from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from sakoda.model import (
    JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
    MOVEMENT_ORDER_ALL_RANDOM,
)
from sakoda.scenarios import DEFAULT_SEEDS, SCENARIO_LIST
from sakoda.validation import (
    build_argument_parser,
    run_validation_suite,
    write_validation_suite,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RETAINED_RUNS_DIR = REPOSITORY_ROOT / "results" / "sakoda" / "runs"
RETAINED_SUMMARY_PATH = (
    REPOSITORY_ROOT / "results" / "sakoda" / "summaries" / "runs.csv"
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"Run record must be a JSON object: {path}")
    return payload


def _scientific_run_fields(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: payload[key]
        for key in (
            "scenario",
            "seed",
            "board",
            "group_size",
            "distance_weight",
            "max_cycles",
            "cycles_completed",
            "stop_reason",
            "attitudes",
            "final_positions",
            "metrics_by_cycle",
            "positions_by_cycle",
        )
    }


class SakodaValidationTests(unittest.TestCase):
    def test_cli_requires_caller_selected_new_output_directory(self) -> None:
        parser = build_argument_parser()
        output_action = next(
            action for action in parser._actions if action.dest == "output_dir"
        )
        self.assertTrue(output_action.required)

        arguments = parser.parse_args(["--output-dir", "tmp/sakoda-results"])
        self.assertEqual(arguments.seeds, list(DEFAULT_SEEDS))
        self.assertIsNone(arguments.scenarios)

        help_text = parser.format_help().lower()
        for excluded in (
            "report",
            "markdown",
            "publication",
            "instructions/",
            "data/csssa2026",
        ):
            with self.subTest(excluded=excluded):
                self.assertNotIn(excluded, help_text)

    def test_writer_refuses_to_overwrite_an_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            existing = Path(temporary_directory) / "existing"
            existing.mkdir()

            with self.assertRaises(FileExistsError):
                write_validation_suite(
                    existing,
                    scenario_names=("crossroads",),
                    seeds=(101,),
                )

    def test_default_suite_generates_all_retained_scenario_seed_results(self) -> None:
        expected_pairs = {
            (scenario.name, seed)
            for scenario in SCENARIO_LIST
            for seed in DEFAULT_SEEDS
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "sakoda-results"
            result = run_validation_suite(output_dir=output_dir)

            self.assertEqual(result["run_count"], len(expected_pairs))
            self.assertEqual(
                {(row["scenario"], row["seed"]) for row in result["summary_rows"]},
                expected_pairs,
            )

            generated_files = {
                path.relative_to(output_dir).as_posix()
                for path in output_dir.rglob("*")
                if path.is_file()
            }
            expected_files = {"summaries/runs.csv"}
            for scenario_name, seed in expected_pairs:
                expected_files.add(f"runs/{scenario_name}_seed_{seed}.json")
                expected_files.add(f"runs/{scenario_name}_seed_{seed}_metrics.csv")
            self.assertEqual(generated_files, expected_files)
            self.assertFalse(
                any(path.suffix == ".md" for path in output_dir.rglob("*"))
            )

            for scenario_name, seed in sorted(expected_pairs):
                stem = f"{scenario_name}_seed_{seed}"
                generated_json = _read_json(output_dir / "runs" / f"{stem}.json")
                retained_json = _read_json(RETAINED_RUNS_DIR / f"{stem}.json")
                with self.subTest(scenario=scenario_name, seed=seed, artifact="json"):
                    self.assertEqual(
                        _scientific_run_fields(generated_json),
                        _scientific_run_fields(retained_json),
                    )
                    self.assertEqual(
                        generated_json["jump_rule"],
                        JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
                    )
                    self.assertEqual(
                        generated_json["jump_rule_description"],
                        retained_json["jump_rule"],
                    )
                    self.assertEqual(
                        generated_json["movement_order"],
                        MOVEMENT_ORDER_ALL_RANDOM,
                    )
                    self.assertEqual(
                        generated_json["movement_order_description"],
                        retained_json["movement_order"],
                    )

                generated_metrics = output_dir / "runs" / f"{stem}_metrics.csv"
                retained_metrics = RETAINED_RUNS_DIR / f"{stem}_metrics.csv"
                with self.subTest(
                    scenario=scenario_name,
                    seed=seed,
                    artifact="metrics",
                ):
                    self.assertEqual(
                        generated_metrics.read_bytes(),
                        retained_metrics.read_bytes(),
                    )

            generated_summary = _read_csv(output_dir / "summaries" / "runs.csv")
            retained_summary = _read_csv(RETAINED_SUMMARY_PATH)
            retained_fields = tuple(retained_summary[0])
            self.assertEqual(len(generated_summary), len(retained_summary))
            self.assertEqual(
                [
                    {field: row[field] for field in retained_fields}
                    for row in generated_summary
                ],
                retained_summary,
            )

    def test_selected_suite_writes_json_metrics_and_summary_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "selected"
            result = run_validation_suite(
                output_dir=output_dir,
                scenario_names=("crossroads",),
                seeds=(101,),
            )

            self.assertEqual(result["run_count"], 1)
            self.assertEqual(result["output_dir"], str(output_dir))
            self.assertEqual(len(result["summary_rows"]), 1)
            self.assertTrue((output_dir / "runs/crossroads_seed_101.json").is_file())
            self.assertTrue(
                (output_dir / "runs/crossroads_seed_101_metrics.csv").is_file()
            )
            self.assertTrue((output_dir / "summaries/runs.csv").is_file())


if __name__ == "__main__":
    unittest.main()
