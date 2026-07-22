from __future__ import annotations

import inspect
import unittest

from yatasterps.config import (
    DEFAULT_YOUTH_COUNT,
    PARAMETER_SPECS,
    PATCH_OPPORTUNITY_MAX,
    PATCH_OPPORTUNITY_MIN,
    PRO_OPP_LAYER_NAME,
    REGION_LAYER_NAME,
    RISK_OPP_LAYER_NAME,
    WORLD_BOUNDS,
    YOUTH_COLORS,
    YOUTH_FACTOR_MAX,
    YOUTH_FACTOR_MIN,
)
from yatasterps.model import YaTASERPSModel


class ModelSetupTests(unittest.TestCase):
    def test_setup_creates_expected_v100_geometry_and_youth_only_population(
        self,
    ) -> None:
        model = YaTASERPSModel(seed=42)
        world_width = WORLD_BOUNDS.max_x - WORLD_BOUNDS.min_x + 1

        self.assertEqual(model.world_size, (33, 41))
        self.assertEqual(len(model.region_positions["home"]), 165)
        self.assertEqual(len(model.region_positions["neighborhood"]), 1023)
        self.assertEqual(len(model.region_positions["school"]), 165)
        self.assertEqual(len(model.region_positions["home"]), 5 * world_width)
        self.assertEqual(len(model.region_positions["neighborhood"]), 31 * world_width)
        self.assertEqual(len(model.region_positions["school"]), 5 * world_width)

        self.assertEqual(len(model.youths), DEFAULT_YOUTH_COUNT)
        self.assertEqual(model.youths_at_home_count, DEFAULT_YOUTH_COUNT)
        self.assertEqual(model.youths_in_neighborhood_count, 0)
        self.assertEqual(model.youths_at_school_count, 0)
        self.assertFalse(hasattr(model, "probation_officers"))

        self.assertEqual(
            set(model.grid.properties),
            {REGION_LAYER_NAME, RISK_OPP_LAYER_NAME, PRO_OPP_LAYER_NAME},
        )
        self.assertTrue(all(youth.location_band == "home" for youth in model.youths))
        self.assertTrue(
            all(youth.visual_color == YOUTH_COLORS["setup"] for youth in model.youths)
        )

    def test_setup_probability_fields_remain_bounded_at_v100_ranges(self) -> None:
        model = YaTASERPSModel(seed=42)

        for values, lower, upper in (
            (
                model.youth_attribute_values("family_risk"),
                YOUTH_FACTOR_MIN,
                YOUTH_FACTOR_MAX,
            ),
            (
                model.youth_attribute_values("family_pro"),
                YOUTH_FACTOR_MIN,
                YOUTH_FACTOR_MAX,
            ),
            (
                model.youth_attribute_values("individual_risk"),
                YOUTH_FACTOR_MIN,
                YOUTH_FACTOR_MAX,
            ),
            (
                model.youth_attribute_values("individual_pro"),
                YOUTH_FACTOR_MIN,
                YOUTH_FACTOR_MAX,
            ),
            (
                model.band_layer_values("school", RISK_OPP_LAYER_NAME),
                PATCH_OPPORTUNITY_MIN,
                PATCH_OPPORTUNITY_MAX,
            ),
            (
                model.band_layer_values("school", PRO_OPP_LAYER_NAME),
                PATCH_OPPORTUNITY_MIN,
                PATCH_OPPORTUNITY_MAX,
            ),
            (
                model.band_layer_values("neighborhood", RISK_OPP_LAYER_NAME),
                PATCH_OPPORTUNITY_MIN,
                PATCH_OPPORTUNITY_MAX,
            ),
            (
                model.band_layer_values("neighborhood", PRO_OPP_LAYER_NAME),
                PATCH_OPPORTUNITY_MIN,
                PATCH_OPPORTUNITY_MAX,
            ),
        ):
            self.assertGreaterEqual(min(values), lower)
            self.assertLessEqual(max(values), upper)

    def test_parameter_surface_is_limited_to_six_v100_sliders(self) -> None:
        expected = {
            "risk_level",
            "promotive_level",
            "schools_risk",
            "schools_promotive",
            "neighborhood_risk",
            "neighborhood_promotive",
        }

        self.assertEqual(set(PARAMETER_SPECS), expected)
        for name, spec in PARAMETER_SPECS.items():
            self.assertEqual(spec.minimum, 1)
            self.assertEqual(spec.maximum, 99)
            self.assertEqual(spec.default, 99)

        signature = inspect.signature(YaTASERPSModel)
        self.assertTrue(expected.issubset(signature.parameters))
        self.assertNotIn("prob_status", signature.parameters)
        self.assertNotIn("num_probs", signature.parameters)

    def test_youth_agents_no_longer_expose_justice_only_fields(self) -> None:
        youth = YaTASERPSModel(seed=42).youths[0]

        for attribute_name in ("caught", "risk_cat", "on_probation", "visits"):
            self.assertFalse(hasattr(youth, attribute_name))


if __name__ == "__main__":
    unittest.main()
