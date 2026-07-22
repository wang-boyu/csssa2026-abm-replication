from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from yatasterps.config import YOUTH_COLORS, netlogo_to_grid
from yatasterps.model import YaTASERPSModel


class ModelScheduleTests(unittest.TestCase):
    def test_step_preserves_expected_daily_trace_and_collects_headline_series(
        self,
    ) -> None:
        model = YaTASERPSModel(num_youth=20, seed=42)

        self.assertEqual(model.current_stage, "ready")
        self.assertEqual(model.current_substep, 0)
        self.assertEqual(model.last_pipeline_trace, [])

        model.step()

        self.assertEqual(model.day, 1)
        self.assertEqual(model.current_stage, "step_day")
        self.assertEqual(model.current_substep, 1)
        self.assertEqual(
            model.last_pipeline_trace,
            [
                "school:1",
                "school:2",
                "school:3",
                "school:4",
                "school:5",
                "school:6",
                "after_school:1",
                "after_school:2",
                "after_school:3",
                "after_school:4",
                "after_school:5",
                "evening:1",
                "evening:2",
                "evening:3",
                "evening:4",
                "step_day:1",
            ],
        )

        dataframe = model.datacollector.get_model_vars_dataframe()
        self.assertEqual(
            list(dataframe.columns),
            ["Percent Antisocial", "Percent Prosocial", "Percent Equal"],
        )
        self.assertEqual(len(dataframe), 2)

    def test_evening_moves_youth_home_before_running_home_logic(self) -> None:
        model = YaTASERPSModel(num_youth=1, seed=42)
        youth = model.youths[0]
        model.grid.move_agent(youth, netlogo_to_grid(0, 0))
        youth.location_band = "neighborhood"
        youth.xcor = 0.0
        youth.ycor = 0.0

        calls: list[tuple[str, int, str]] = []
        original = model._youth_at_home

        def wrapped(agent) -> None:
            calls.append(
                (model.current_stage, model.current_substep, agent.location_band)
            )
            original(agent)

        model._youth_at_home = wrapped

        model.evening()

        self.assertEqual(
            calls,
            [("evening", 2, "home"), ("evening", 3, "home"), ("evening", 4, "home")],
        )
        self.assertEqual(youth.location_band, "home")

    def test_neighborhood_movement_uses_continuous_netlogo_style_coordinates(
        self,
    ) -> None:
        model = YaTASERPSModel(num_youth=1, seed=42)
        youth = model.youths[0]
        model.grid.move_agent(youth, netlogo_to_grid(0, 0))
        youth.location_band = "neighborhood"
        youth.xcor = 0.0
        youth.ycor = 0.0
        youth.heading_degrees = 10

        with patch.object(model.random, "random", return_value=1.0):
            model._move_youth_within_neighborhood(youth)

        self.assertAlmostEqual(youth.xcor, math.sin(math.radians(10)), places=6)
        self.assertAlmostEqual(youth.ycor, math.cos(math.radians(10)), places=6)
        self.assertEqual(youth.pos, netlogo_to_grid(0, 1))

    def test_model_has_no_legacy_180_day_family_cadence_state(self) -> None:
        model = YaTASERPSModel(seed=42)

        for attribute_name in (
            "family_cadence_days",
            "family_influence_days_applied",
            "last_family_influence_day",
            "family_influence_due_today",
            "next_family_influence_day",
            "_apply_family_influence_if_due",
        ):
            self.assertFalse(hasattr(model, attribute_name))

    def test_evening_refreshes_youth_visuals_to_v100_colors(self) -> None:
        model = YaTASERPSModel(num_youth=2, seed=42)
        antisocial_youth, prosocial_youth = model.youths[:2]

        antisocial_youth.location_band = "home"
        antisocial_youth.antisocial = 1.0
        antisocial_youth.prosocial = 0.0
        antisocial_youth.visual_color = YOUTH_COLORS["setup"]

        prosocial_youth.location_band = "home"
        prosocial_youth.antisocial = 0.0
        prosocial_youth.prosocial = 0.0
        prosocial_youth.visual_color = YOUTH_COLORS["setup"]

        model.evening()

        self.assertEqual(antisocial_youth.visual_color, YOUTH_COLORS["antisocial"])
        self.assertEqual(prosocial_youth.visual_color, YOUTH_COLORS["prosocial"])


if __name__ == "__main__":
    unittest.main()
