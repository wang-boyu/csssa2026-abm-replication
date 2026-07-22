from __future__ import annotations

import inspect
import re
import unittest

from sakoda import app as sakoda_app
from sakoda.app import (
    MAIN_CONVENTION_LABEL,
    board_cells,
    board_grid_style,
    convention_for_label,
    convention_options,
    create_model,
    latest_metrics,
    scenario_label,
    scenario_name_from_label,
    scenario_options,
)
from sakoda.model import (
    JUMP_RULE_ENDPOINT_ONLY,
    JUMP_RULE_NO_ADJACENT_AVAILABLE,
    JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
    MOVEMENT_ORDER_ALL_RANDOM,
    MOVEMENT_ORDER_GROUPS_SEQUENTIAL,
    SakodaModel,
)
from sakoda.scenarios import CROSSES, SQUARES

EXPECTED_SCENARIO_OPTIONS = [
    {"name": "crossroads", "label": "Crossroads"},
    {"name": "mutual_suspicion", "label": "Mutual Suspicion"},
    {"name": "segregation", "label": "Segregation"},
    {"name": "social_climber", "label": "Social Climber"},
    {"name": "social_worker", "label": "Social Worker"},
    {"name": "boy_girl", "label": "Boy-Girl"},
    {"name": "couples", "label": "Couples"},
    {"name": "husband_wives", "label": "Husbands and Wives"},
]


def _css_rule(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}", css)
    if match is None:
        raise AssertionError(f"Missing CSS rule for {selector!r}.")
    return match.group("body")


class SakodaAppHelperTests(unittest.TestCase):
    def test_responsive_controls_wrap_without_forcing_button_overflow(self) -> None:
        toggle_rule = _css_rule(sakoda_app.SAKODA_CSS, ".sakoda-mode-toggle")
        toggle_button_rule = _css_rule(
            sakoda_app.SAKODA_CSS,
            ".sakoda-mode-toggle .v-btn",
        )
        toggle_content_rule = _css_rule(
            sakoda_app.SAKODA_CSS,
            ".sakoda-mode-toggle .v-btn__content",
        )
        action_rule = _css_rule(
            sakoda_app.SAKODA_CSS,
            ".sakoda-control-actions",
        )
        action_button_rule = _css_rule(
            sakoda_app.SAKODA_CSS,
            ".sakoda-control-actions .v-btn",
        )

        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", toggle_rule)
        self.assertIn("max-width: 100%", toggle_rule)
        self.assertIn("min-width: 0", toggle_button_rule)
        self.assertIn("max-width: 100%", toggle_button_rule)
        self.assertIn("white-space: normal", toggle_content_rule)
        self.assertIn("overflow-wrap: anywhere", toggle_content_rule)
        self.assertIn("flex-wrap: wrap", action_rule)
        self.assertIn("width: 100%", action_rule)
        self.assertIn("min-width: 0", action_button_rule)

        page_source = inspect.getsource(sakoda_app.page)
        self.assertIn('classes=["sakoda-mode-toggle"]', page_source)
        self.assertIn('classes=["sakoda-control-actions"]', page_source)

    def test_scenario_options_cover_all_source_labels(self) -> None:
        options = scenario_options()

        self.assertEqual(options, EXPECTED_SCENARIO_OPTIONS)
        self.assertEqual(len(options), 8)
        self.assertIn("Husbands and Wives", [option["label"] for option in options])

    def test_default_create_model_uses_main_evidence_convention(self) -> None:
        model = create_model()

        self.assertEqual(model.scenario.name, "crossroads")
        self.assertEqual(model.seed_value, 101)
        self.assertEqual(model.jump_rule, JUMP_RULE_NO_ADJACENT_IMPROVEMENT)
        self.assertEqual(model.movement_order, MOVEMENT_ORDER_ALL_RANDOM)

    def test_board_cells_describe_default_board_and_piece_labels(self) -> None:
        cells = board_cells(create_model())
        occupied = [cell for cell in cells if cell["occupied"]]

        self.assertEqual(len(cells), 64)
        self.assertEqual(len(occupied), 12)
        self.assertEqual({cell["row"] for cell in cells}, set(range(1, 9)))
        self.assertEqual({cell["column"] for cell in cells}, set(range(1, 9)))
        self.assertTrue(all(1 <= cell["row"] <= 8 for cell in cells))
        self.assertTrue(all(1 <= cell["column"] <= 8 for cell in cells))
        self.assertEqual(
            sorted(cell["label"] for cell in occupied if cell["group"] == SQUARES),
            ["S1", "S2", "S3", "S4", "S5", "S6"],
        )
        self.assertEqual(
            sorted(cell["label"] for cell in occupied if cell["group"] == CROSSES),
            ["X1", "X2", "X3", "X4", "X5", "X6"],
        )
        self.assertEqual(
            {cell["symbol"] for cell in occupied if cell["group"] == SQUARES},
            {"square"},
        )
        self.assertEqual(
            {cell["symbol"] for cell in occupied if cell["group"] == CROSSES},
            {"cross"},
        )

    def test_board_grid_style_uses_equal_columns_and_rows(self) -> None:
        default_style = board_grid_style(create_model())

        self.assertIn(
            "grid-template-columns: repeat(8, minmax(0, 1fr));",
            default_style,
        )
        self.assertIn(
            "grid-template-rows: repeat(8, minmax(0, 1fr));",
            default_style,
        )

        small_model = SakodaModel(
            "crossroads",
            seed=11,
            rows=3,
            columns=4,
            group_size=2,
            initial_positions={
                (SQUARES, 1): (1, 1),
                (SQUARES, 2): (1, 2),
                (CROSSES, 1): (3, 3),
                (CROSSES, 2): (3, 4),
            },
        )
        small_style = board_grid_style(small_model)

        self.assertIn(
            "grid-template-columns: repeat(4, minmax(0, 1fr));",
            small_style,
        )
        self.assertIn(
            "grid-template-rows: repeat(3, minmax(0, 1fr));",
            small_style,
        )

    def test_latest_metrics_tracks_initial_and_stepped_cycle(self) -> None:
        model = create_model()

        initial_metrics = latest_metrics(model)
        self.assertEqual(initial_metrics["cycle"], 0)
        self.assertEqual(initial_metrics["movement_count"], 0)

        model.step()
        stepped_metrics = latest_metrics(model)

        self.assertEqual(stepped_metrics, model.metrics_by_cycle[-1])
        self.assertEqual(stepped_metrics["cycle"], 1)
        self.assertEqual(stepped_metrics["cycle"], model.cycle)
        self.assertGreater(stepped_metrics["movement_count"], 0)
        self.assertNotEqual(
            stepped_metrics["movement_count"],
            initial_metrics["movement_count"],
        )

    def test_convention_options_distinguish_main_and_diagnostic_presets(self) -> None:
        options = convention_options()
        main_options = [
            option for option in options if option["role"] == "main evidence"
        ]
        diagnostic_options = [
            option for option in options if option["role"] == "diagnostic/supporting"
        ]

        self.assertEqual(len(options), 4)
        self.assertEqual(len(main_options), 1)
        self.assertEqual(main_options[0]["label"], MAIN_CONVENTION_LABEL)
        self.assertEqual(
            main_options[0]["jump_rule"],
            JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
        )
        self.assertEqual(main_options[0]["movement_order"], MOVEMENT_ORDER_ALL_RANDOM)
        self.assertEqual(len(diagnostic_options), 3)
        self.assertTrue(
            all(
                option["label"].startswith("Diagnostic/supporting: ")
                for option in diagnostic_options
            )
        )
        self.assertEqual(
            {
                (option["jump_rule"], option["movement_order"])
                for option in diagnostic_options
            },
            {
                (JUMP_RULE_NO_ADJACENT_AVAILABLE, MOVEMENT_ORDER_ALL_RANDOM),
                (JUMP_RULE_ENDPOINT_ONLY, MOVEMENT_ORDER_ALL_RANDOM),
                (
                    JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
                    MOVEMENT_ORDER_GROUPS_SEQUENTIAL,
                ),
            },
        )
        self.assertEqual(convention_for_label(MAIN_CONVENTION_LABEL), main_options[0])

    def test_scenario_label_and_name_round_trip_or_raise(self) -> None:
        for option in EXPECTED_SCENARIO_OPTIONS:
            name = option["name"]
            label = option["label"]
            self.assertEqual(scenario_label(name), label)
            self.assertEqual(scenario_name_from_label(label), name)

        with self.assertRaisesRegex(ValueError, "Unknown Sakoda scenario 'bogus'"):
            scenario_label("bogus")
        with self.assertRaisesRegex(
            ValueError,
            "Unknown Sakoda scenario label 'Bogus'",
        ):
            scenario_name_from_label("Bogus")


if __name__ == "__main__":
    unittest.main()
