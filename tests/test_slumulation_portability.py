from __future__ import annotations

import csv
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from slumulation import constants, runner, summaries, validation

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SLUMULATION_RESULTS = REPOSITORY_ROOT / "results/slumulation"
RETAINED_SUMMARIES = SLUMULATION_RESULTS / "summaries"


def _csv_header(path: Path) -> tuple[str, ...]:
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(next(csv.reader(handle)))


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class PortablePathAndCliTests(unittest.TestCase):
    def test_netlogo_paths_and_hashes_match_included_files(self) -> None:
        self.assertEqual(
            constants.PROVENANCE_NETLOGO_SOURCE,
            Path("references/slumulation/Slumulation_OriginalModel_NetLogo4_2.nlogo"),
        )
        self.assertEqual(
            constants.EXECUTION_REFERENCE_NETLOGO_SOURCE,
            Path("references/slumulation/Slumulation_NetLogo6_1.nlogo"),
        )
        self.assertEqual(
            constants.NETLOGO_RESULTS_DIR,
            Path("results/slumulation/netlogo"),
        )
        for relative_path, expected_hash in constants.NETLOGO_SOURCE_SHA256.items():
            with self.subTest(path=relative_path):
                path = REPOSITORY_ROOT / relative_path
                self.assertTrue(path.is_file())
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(), expected_hash
                )

    def test_default_summary_inputs_use_the_public_results_layout(self) -> None:
        expected_paths = {
            summaries.DEFAULT_NETLOGO_PATCH_SIZES: (
                Path("results/slumulation/netlogo/slum_size_patch_sizes.csv")
            ),
            summaries.DEFAULT_MESA_PATCH_SIZES: (
                Path("results/slumulation/mesa/slum_size_patch_sizes.csv")
            ),
        }

        for actual, expected in expected_paths.items():
            with self.subTest(path=actual):
                self.assertEqual(actual, expected)
                self.assertTrue((REPOSITORY_ROOT / actual).is_file())
                self.assertNotIn("data", actual.parts)
                self.assertFalse(
                    any(part.endswith(("_v1", "_v2")) for part in actual.parts)
                )

    def test_public_module_parsers_require_caller_selected_output_dirs(self) -> None:
        output_dir = Path("tmp/slumulation-check")
        runner_args = runner.build_argument_parser().parse_args(
            [
                "--output-dir",
                str(output_dir / "mesa"),
                "--repetitions",
                "2",
                "--max-steps",
                "3",
            ]
        )
        validation_args = validation.build_argument_parser().parse_args(
            [
                "--mesa-dir",
                str(output_dir / "mesa"),
                "--netlogo-dir",
                str(SLUMULATION_RESULTS / "netlogo"),
                "--output-dir",
                str(output_dir / "summaries"),
            ]
        )
        summary_args = summaries.build_argument_parser().parse_args(
            ["--output-dir", str(output_dir / "slum-size")]
        )

        self.assertEqual(runner_args.output_dir, output_dir / "mesa")
        self.assertEqual(runner_args.repetitions, 2)
        self.assertEqual(runner_args.max_steps, 3)
        self.assertEqual(validation_args.mesa_dir, output_dir / "mesa")
        self.assertEqual(validation_args.netlogo_dir, SLUMULATION_RESULTS / "netlogo")
        self.assertEqual(validation_args.output_dir, output_dir / "summaries")
        self.assertEqual(summary_args.output_dir, output_dir / "slum-size")

        for parser in (
            runner.build_argument_parser(),
            validation.build_argument_parser(),
            summaries.build_argument_parser(),
        ):
            with self.subTest(prog=parser.prog):
                with self.assertRaises(SystemExit):
                    parser.parse_args([])

    def test_public_writers_do_not_replace_existing_output_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            runner_output = root / "runner"
            summary_output = root / "summary"
            validation_output = root / "validation"
            runner_output.mkdir()
            summary_output.mkdir()
            validation_output.mkdir()

            with self.assertRaises(FileExistsError):
                runner.write_selected_mesa_surface(
                    runner_output,
                    repetitions=1,
                    max_steps=0,
                )
            with self.assertRaises(FileExistsError):
                summaries.write_slum_size_summaries(summary_output)
            with self.assertRaises(FileExistsError):
                validation.main(
                    [
                        "--mesa-dir",
                        str(SLUMULATION_RESULTS / "mesa"),
                        "--netlogo-dir",
                        str(SLUMULATION_RESULTS / "netlogo"),
                        "--output-dir",
                        str(validation_output),
                    ]
                )

    def test_removed_publication_modules_and_app_triptych_are_absent(self) -> None:
        app = importlib.import_module("slumulation.app")
        self.assertFalse(hasattr(app, "triptych_panel"))

        for module_name in (
            "slumulation.evidence",
            "slumulation.evidence_targets",
            "slumulation.publication_visuals",
            "slumulation.qualitative_review",
            "slumulation.spatial_publication",
        ):
            with self.subTest(module=module_name):
                self.assertIsNone(importlib.util.find_spec(module_name))


class PortableRegenerationTests(unittest.TestCase):
    def test_reduced_runner_surface_covers_all_three_experiment_families(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "mesa"
            result = runner.write_selected_mesa_surface(
                output_dir,
                repetitions=1,
                max_steps=1,
            )

            outputs = {output.experiment_name: output for output in result.outputs}
            self.assertEqual(set(outputs), set(constants.SELECTED_EXPERIMENT_NAMES))
            self.assertEqual(len(result.seed_manifest), 8)
            self.assertEqual(
                {
                    name: output.parameter_condition_count
                    for name, output in outputs.items()
                },
                {
                    "Typical Run": 1,
                    "Population Growth Rate": 3,
                    "Politics and Development ON OFF": 4,
                },
            )
            self.assertEqual(
                {name: output.row_count for name, output in outputs.items()},
                {
                    "Typical Run": 2,
                    "Population Growth Rate": 6,
                    "Politics and Development ON OFF": 8,
                },
            )
            self.assertEqual(
                {output.output_path.name for output in result.outputs},
                {"baseline.csv", "population_growth.csv", "politics_development.csv"},
            )
            resolved_output_dir = output_dir.resolve()
            self.assertTrue(
                all(
                    output.output_path.parent == resolved_output_dir
                    for output in result.outputs
                )
            )
            for output in result.outputs:
                with self.subTest(experiment=output.experiment_name):
                    self.assertEqual(
                        _csv_header(output.output_path),
                        constants.BEHAVIORSPACE_OUTPUT_COLUMNS,
                    )

            self.assertEqual(result.manifest_path, resolved_output_dir / "seeds.json")
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["entries"]), 8)

    def test_generic_comparison_summaries_regenerate_byte_identically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "summaries"
            result = validation.write_comparison_outputs(
                SLUMULATION_RESULTS / "mesa",
                output_dir,
                netlogo_reference_dir=SLUMULATION_RESULTS / "netlogo",
            )

            generated = {
                "final_step.csv": result.final_step_path,
                "trajectories.csv": result.trajectories_path,
                "supporting_trajectories.csv": result.supporting_trajectories_path,
            }
            self.assertEqual(result.comparison_dir, output_dir)
            self.assertEqual(result.experiments, constants.SELECTED_EXPERIMENT_NAMES)
            for filename, path in generated.items():
                with self.subTest(filename=filename):
                    self.assertEqual(path.parent, output_dir)
                    self.assertEqual(
                        path.read_bytes(),
                        (RETAINED_SUMMARIES / filename).read_bytes(),
                    )

            final_rows = _csv_rows(result.final_step_path)
            trajectory_rows = _csv_rows(result.trajectories_path)
            supporting_rows = _csv_rows(result.supporting_trajectories_path)
            self.assertEqual(
                {row["experiment"] for row in final_rows},
                set(constants.SELECTED_EXPERIMENT_NAMES),
            )
            self.assertEqual(
                {row["metric"] for row in final_rows},
                set(constants.PRIMARY_VALIDATION_METRICS),
            )
            self.assertTrue(trajectory_rows)
            self.assertEqual(
                {row["metric"] for row in supporting_rows},
                set(
                    constants.SUPPORTING_METRIC_NAMES + constants.RAW_ONLY_METRIC_NAMES
                ),
            )

    def test_slum_size_summaries_regenerate_byte_identically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "slum-size"
            result = summaries.write_slum_size_summaries(output_dir)

            self.assertEqual(result.output_dir, output_dir.resolve())
            expected = {
                result.distribution_by_run_path: (
                    RETAINED_SUMMARIES / "slum_size_distribution_by_run.csv"
                ),
                result.distribution_path: (
                    RETAINED_SUMMARIES / "slum_size_distribution.csv"
                ),
            }
            for generated, retained in expected.items():
                with self.subTest(path=generated.name):
                    self.assertEqual(generated.parent, output_dir.resolve())
                    self.assertEqual(generated.read_bytes(), retained.read_bytes())

            self.assertEqual(
                _csv_header(result.distribution_by_run_path),
                (
                    "engine",
                    "run_number",
                    "seed",
                    "bin",
                    "patch_count",
                    "run_patch_total",
                    "probability",
                ),
            )
            self.assertEqual(
                _csv_header(result.distribution_path),
                ("engine", "bin", "run_count", "mean_probability"),
            )
            self.assertEqual(
                {row["engine"] for row in _csv_rows(result.distribution_path)},
                {"netlogo", "mesa"},
            )


if __name__ == "__main__":
    unittest.main()
