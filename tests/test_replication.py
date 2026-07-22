from __future__ import annotations

import csv
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from yatasterps.replication import (
    INCLUDED_MESA_RAW_RUNS_PATH,
    INCLUDED_NETLOGO_RAW_RUNS_PATH,
    INCLUDED_SUMMARIES_DIR,
    NETLOGO_FINAL_VALUE_FIELD_MAP,
    PAPER_PARAMETER_LEVELS,
    RESULTS_DIR,
    ParameterBundle,
    build_sweep_artifacts,
    generate_parameter_manifest,
    main,
    parse_args,
    parse_netlogo_runs,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRESERVED_MANIFEST_PATH = RESULTS_DIR / "runs" / "parameter_manifest.csv"


class ReplicationHarnessTests(unittest.TestCase):
    @staticmethod
    def _write_netlogo_fixture(path: Path) -> None:
        required_labels = [name for name, _ in NETLOGO_FINAL_VALUE_FIELD_MAP]
        final_value_labels = required_labels + [
            f"unused-{index}" for index in range(38 - len(required_labels))
        ]
        run_specs = (
            {
                "run_number": 1,
                "params": (25, 25, 25, 25, 25, 25),
                "percent": 0.4,
            },
            {
                "run_number": 2,
                "params": (25, 25, 25, 25, 25, 25),
                "percent": 0.6,
            },
            {
                "run_number": 3,
                "params": (25, 25, 25, 25, 50, 25),
                "percent": 0.5,
            },
        )
        width = 1 + (38 * len(run_specs))
        rows = [[""] * width for _ in range(17)]
        parameter_names = (
            "promotive-level",
            "risk-level",
            "schools-promotive",
            "schools-risk",
            "neighborhood-promotive",
            "neighborhood-risk",
        )

        rows[6][0] = "[run number]"
        for row_index, parameter_name in enumerate(parameter_names, start=7):
            rows[row_index][0] = parameter_name
        rows[15] = ["[final value]", *final_value_labels]

        for run_index, run in enumerate(run_specs):
            block_start = 1 + (run_index * 38)
            rows[6][block_start] = str(run["run_number"])
            for parameter_offset, parameter_value in enumerate(run["params"]):
                rows[7 + parameter_offset][block_start] = str(parameter_value)

            required_values = {
                "[step]": 1800,
                "count turtles with [antisocial > prosocial] / count turtles": run[
                    "percent"
                ],
                "mean [prosocial] of turtles": 100.0 + run_index,
                "mean [antisocial] of turtles": 150.0 + run_index,
                "mean [family-risk] of turtles": 0.31 + (run_index / 100),
                "mean [family-pro] of turtles": 0.32 + (run_index / 100),
                "mean [risk-opp] of school-patches": 0.33 + (run_index / 100),
                "mean [pro-opp] of school-patches": 0.34 + (run_index / 100),
                "mean [risk-opp] of neighborhood-patches": 0.35 + (run_index / 100),
                "mean [pro-opp] of neighborhood-patches": 0.36 + (run_index / 100),
            }
            for label_offset, label in enumerate(final_value_labels):
                rows[16][block_start + label_offset] = str(
                    required_values.get(label, 0)
                )

        with path.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(rows)

    def test_parameter_manifest_has_expected_bundle_surface(self) -> None:
        bundles = generate_parameter_manifest()

        self.assertEqual(len(bundles), 729)
        self.assertEqual(bundles[0].bundle_id, 1)
        self.assertEqual(bundles[-1].bundle_id, 729)
        self.assertEqual(bundles[0].promotive_level, 25)
        self.assertEqual(bundles[-1].neighborhood_risk, 75)
        self.assertEqual(PAPER_PARAMETER_LEVELS, (25, 50, 75))

    def test_manifest_cli_regenerates_preserved_file_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "manifest-output"
            stdout = StringIO()
            with redirect_stdout(stdout):
                main(
                    [
                        "--write-manifest-only",
                        "--output-dir",
                        str(output_dir),
                    ]
                )

            report = json.loads(stdout.getvalue())
            generated_path = output_dir / "runs" / "parameter_manifest.csv"
            self.assertEqual(report["bundle_count"], 729)
            self.assertEqual(Path(report["manifest_path"]), generated_path.resolve())
            self.assertEqual(
                generated_path.read_bytes(),
                PRESERVED_MANIFEST_PATH.read_bytes(),
            )

    def test_parse_netlogo_runs_reconstructs_bundles_and_repetitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "netlogo-export.csv"
            self._write_netlogo_fixture(source_path)
            rows = parse_netlogo_runs(source_path)

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["bundle_id"], 1)
        self.assertEqual(rows[0]["repetition"], 1)
        self.assertEqual(rows[1]["bundle_id"], 1)
        self.assertEqual(rows[1]["repetition"], 2)
        self.assertNotEqual(rows[2]["bundle_id"], rows[0]["bundle_id"])
        self.assertEqual(rows[2]["repetition"], 1)
        self.assertEqual(rows[2]["neighborhood_promotive"], 50)
        self.assertEqual(rows[2]["total_steps"], 1800)

    def test_summary_cli_regenerates_four_preserved_files_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "summary-output"
            stdout = StringIO()
            with redirect_stdout(stdout):
                main(["--summarize-runs", "--output-dir", str(output_dir)])

            report = json.loads(stdout.getvalue())
            self.assertEqual(
                Path(report["mesa_raw_runs_path"]),
                INCLUDED_MESA_RAW_RUNS_PATH.resolve(),
            )
            self.assertEqual(
                Path(report["netlogo_raw_runs_path"]),
                INCLUDED_NETLOGO_RAW_RUNS_PATH.resolve(),
            )

            expected_names = {
                "prosocial_mesa.csv",
                "antisocial_mesa.csv",
                "prosocial_netlogo.csv",
                "antisocial_netlogo.csv",
            }
            generated_names = {Path(path).name for path in report["summary_paths"]}
            self.assertSetEqual(generated_names, expected_names)
            for filename in expected_names:
                with self.subTest(filename=filename):
                    self.assertEqual(
                        (output_dir / "summaries" / filename).read_bytes(),
                        (INCLUDED_SUMMARIES_DIR / filename).read_bytes(),
                    )

    def test_reduced_sweep_writes_run_data_to_caller_selected_directory(
        self,
    ) -> None:
        bundles = [
            ParameterBundle(
                bundle_id=index,
                promotive_level=level,
                risk_level=level,
                schools_promotive=level,
                schools_risk=level,
                neighborhood_promotive=level,
                neighborhood_risk=level,
            )
            for index, level in enumerate(PAPER_PARAMETER_LEVELS, start=1)
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "caller-selected-output"
            with (
                patch(
                    "yatasterps.replication.generate_parameter_manifest",
                    return_value=bundles,
                ),
                patch("yatasterps.replication.ProcessPoolExecutor") as executor_class,
            ):
                executor = executor_class.return_value.__enter__.return_value
                executor.map.side_effect = lambda function, tasks, chunksize: map(
                    function, tasks
                )
                report = build_sweep_artifacts(
                    output_dir=output_dir,
                    max_ticks=1,
                    seeds=(7, 8),
                    workers=1,
                )

            raw_runs_path = output_dir / "runs" / "mesa_raw_runs.csv"
            with raw_runs_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(report["bundle_count"], 3)
            self.assertEqual(report["seed_count"], 2)
            self.assertEqual(report["run_count"], 6)
            self.assertEqual(Path(report["raw_runs_path"]), raw_runs_path.resolve())
            self.assertEqual(len(rows), 6)
            self.assertEqual({int(row["seed"]) for row in rows}, {7, 8})
            self.assertTrue((output_dir / "runs" / "parameter_manifest.csv").is_file())
            self.assertTrue((output_dir / "summaries" / "prosocial_mesa.csv").is_file())
            self.assertTrue(
                (output_dir / "summaries" / "antisocial_mesa.csv").is_file()
            )

    def test_cli_help_and_defaults_describe_retained_actions(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as context:
            parse_args(["--help"])

        self.assertEqual(context.exception.code, 0)
        help_text = stdout.getvalue()
        for action in (
            "--run-sweep",
            "--summarize-runs",
            "--parse-netlogo-runs",
            "--write-manifest-only",
        ):
            self.assertIn(action, help_text)
        for removed_term in ("figure", "three-way", "table3"):
            self.assertNotIn(removed_term, help_text.lower())

        with tempfile.TemporaryDirectory() as tmpdir:
            args = parse_args(
                [
                    "--summarize-runs",
                    "--output-dir",
                    str(Path(tmpdir) / "summaries"),
                ]
            )
        self.assertTrue(args.summarize_runs)
        self.assertEqual(args.mesa_raw_runs, INCLUDED_MESA_RAW_RUNS_PATH)
        self.assertEqual(args.netlogo_raw_runs, INCLUDED_NETLOGO_RAW_RUNS_PATH)

    def test_cli_rejects_missing_action_and_protected_or_nonempty_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            nonempty_output = root / "nonempty"
            nonempty_output.mkdir()
            sentinel = nonempty_output / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")

            invalid_argument_sets = (
                ["--output-dir", str(root / "no-action")],
                [
                    "--write-manifest-only",
                    "--output-dir",
                    str(nonempty_output),
                ],
                [
                    "--write-manifest-only",
                    "--output-dir",
                    str(RESULTS_DIR / "generated"),
                ],
                [
                    "--parse-netlogo-runs",
                    "--output-dir",
                    str(root / "missing-source"),
                ],
            )
            for arguments in invalid_argument_sets:
                with self.subTest(arguments=arguments):
                    with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                        parse_args(arguments)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_included_run_inputs_use_public_results_layout(self) -> None:
        self.assertEqual(
            INCLUDED_MESA_RAW_RUNS_PATH,
            REPOSITORY_ROOT / "results" / "yatasterps" / "runs" / "mesa_raw_runs.csv",
        )
        self.assertEqual(
            INCLUDED_NETLOGO_RAW_RUNS_PATH,
            REPOSITORY_ROOT
            / "results"
            / "yatasterps"
            / "runs"
            / "netlogo_raw_runs.csv",
        )
        self.assertTrue(INCLUDED_MESA_RAW_RUNS_PATH.is_file())
        self.assertTrue(INCLUDED_NETLOGO_RAW_RUNS_PATH.is_file())


if __name__ == "__main__":
    unittest.main()
