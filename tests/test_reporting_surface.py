from __future__ import annotations

import ast
import importlib
import inspect
import os
from pathlib import Path
import runpy
import tempfile
import textwrap
import unittest
from functools import lru_cache


@lru_cache(maxsize=1)
def _load_reporting_modules():
    mpl_config_dir = Path(tempfile.gettempdir()) / "yatasterps-test-mpl"
    mpl_config_dir.mkdir(exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_config_dir))

    app_module = importlib.import_module("yatasterps.app")
    config_module = importlib.import_module("yatasterps.config")
    model_module = importlib.import_module("yatasterps.model")
    return app_module, config_module.PARAMETER_SPECS, model_module.YaTASERPSModel


class ReportingSurfaceTests(unittest.TestCase):
    def test_app_loads_as_a_solara_file_path_entrypoint(self) -> None:
        app_path = Path(__file__).resolve().parents[1] / "yatasterps" / "app.py"

        namespace = runpy.run_path(
            app_path,
            run_name="yatasterps_file_entrypoint",
        )

        self.assertIn("page", namespace)

    def test_model_params_match_the_six_slider_v100_surface(self) -> None:
        app, parameter_specs, _ = _load_reporting_modules()
        expected_keys = [
            "risk_level",
            "promotive_level",
            "schools_risk",
            "schools_promotive",
            "neighborhood_risk",
            "neighborhood_promotive",
        ]

        self.assertEqual(list(app.MODEL_PARAMS), expected_keys)
        self.assertNotIn("num_probs", app.MODEL_PARAMS)
        self.assertNotIn("prob_status", app.MODEL_PARAMS)

        for key in expected_keys:
            parameter = app.MODEL_PARAMS[key]
            spec = parameter_specs[key]
            self.assertEqual(parameter["label"], key.replace("_", "-"))
            self.assertEqual(parameter["value"], spec.default)
            self.assertEqual(parameter["min"], spec.minimum)
            self.assertEqual(parameter["max"], spec.maximum)
            self.assertEqual(parameter["step"], spec.step)

    def test_headline_plot_series_match_v100_plot_pens(self) -> None:
        app, _, model_class = _load_reporting_modules()
        self.assertEqual(
            list(app.HEADLINE_COLORS),
            ["Percent Antisocial", "Percent Prosocial", "Percent Equal"],
        )

        model = model_class(seed=42)
        self.assertEqual(
            list(model.datacollector.model_reporters),
            list(app.HEADLINE_COLORS),
        )

    def test_family_risk_chart_uses_actual_family_risk_values(self) -> None:
        app, _, _ = _load_reporting_modules()
        source = textwrap.dedent(inspect.getsource(app.dashboard_panel))
        tree = ast.parse(source)
        card_series_sources: dict[str, str] = {}

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "histogram_card":
                continue
            if not node.args:
                continue
            if not isinstance(node.args[0], ast.Constant):
                continue
            if not isinstance(node.args[0].value, str):
                continue

            title = node.args[0].value
            series_source = ast.get_source_segment(source, node.args[1]) or ""
            card_series_sources[title] = series_source

        self.assertIn("Family Risk", card_series_sources)
        self.assertIn(
            'model.youth_attribute_values("family_risk")',
            card_series_sources["Family Risk"],
        )
        self.assertNotIn("family_pro", card_series_sources["Family Risk"])
        self.assertIn(
            'model.youth_attribute_values("family_pro")',
            card_series_sources["Family Promotive"],
        )


if __name__ == "__main__":
    unittest.main()
