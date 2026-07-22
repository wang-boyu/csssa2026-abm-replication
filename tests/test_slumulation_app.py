from __future__ import annotations

import asyncio
from contextlib import ExitStack, nullcontext
import importlib
import inspect
import re
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from slumulation import (
    DeveloperState,
    HouseholdState,
    build_empty_world,
    constants,
)
from slumulation.dynamics import SlumulateStepResult

EXPECTED_EXPERIMENT_OPTIONS = [
    {"name": "Typical Run", "label": "Typical Run"},
    {"name": "Population Growth Rate", "label": "Population Growth Rate"},
    {
        "name": "Politics and Development ON OFF",
        "label": "Politics and Development ON OFF",
    },
]
EXPECTED_PARAMETER_COUNTS = {
    "Typical Run": 1,
    "Population Growth Rate": 3,
    "Politics and Development ON OFF": 4,
}
PRIOR_DIAGNOSTIC_LAYER_NAMES = (
    "slum_status",
    "rent",
    "ward",
    "occupancy",
    "resicat",
)
EXPECTED_LAYER_NAMES = ("composite", *PRIOR_DIAGNOSTIC_LAYER_NAMES, "developers")
EXPECTED_APP_EXPORTS = (
    "DEFAULT_EXPERIMENT_NAME",
    "DEFAULT_SEED",
    "DEFAULT_LAYER_NAME",
    "DEFAULT_RUN_STEPS",
    "LAYER_OPTIONS",
    "SlumulationAppState",
    "experiment_options",
    "experiment_spec_for_name",
    "parameter_condition_options",
    "parameter_combination_for_index",
    "create_app_state",
    "step_app_state",
    "run_app_steps",
    "patch_grid",
    "patch_grid_style",
    "cell_style",
    "layer_options",
    "metric_items",
    "format_metric_value",
)


def _app_api() -> SimpleNamespace:
    app = importlib.import_module("slumulation.app")
    missing = [name for name in EXPECTED_APP_EXPORTS if not hasattr(app, name)]

    if missing:
        raise AssertionError(
            f"slumulation.app is missing expected public exports: {missing!r}"
        )

    return SimpleNamespace(
        module=app,
        **{name: getattr(app, name) for name in EXPECTED_APP_EXPORTS},
    )


def _call_with_supported_keywords(function, **kwargs):
    signature = inspect.signature(function)

    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return function(**kwargs)

    supported_kwargs = {
        name: value for name, value in kwargs.items() if name in signature.parameters
    }
    return function(**supported_kwargs)


def _option_names(options) -> tuple[str, ...]:
    return tuple(
        option["name"] if isinstance(option, dict) else option.name
        for option in options
    )


def _option_labels(options) -> tuple[str, ...]:
    labels = []
    for option in options:
        if isinstance(option, dict):
            if "label" in option:
                labels.append(option["label"])
            else:
                labels.append(option["name"])
        else:
            if hasattr(option, "label"):
                labels.append(option.label)
            else:
                labels.append(option.name)
    return tuple(labels)


def _parameter_values(combination) -> dict[str, object]:
    if isinstance(combination, dict):
        values = combination.get("parameter_values", combination.get("parameters"))
        return dict(values if values is not None else combination)

    for name in ("parameter_values", "parameters"):
        if hasattr(combination, name):
            return dict(getattr(combination, name))

    return dict(combination)


def _flatten_grid(grid) -> list[dict[str, object]]:
    return [cell for row in grid for cell in row]


def _cell_at(grid, x: int, y: int) -> dict[str, object]:
    return next(
        cell
        for cell in _flatten_grid(grid)
        if int(cell["x"]) == x and int(cell["y"]) == y
    )


def _sample_cell(**overrides: object) -> dict[str, object]:
    cell: dict[str, object] = {
        "x": 0,
        "y": 0,
        "ward": 5,
        "rent": 320.0,
        "rent_payable": 320.0,
        "occupied": True,
        "occupancy": 4,
        "num_occupants": 4,
        "num_units": 4,
        "available": False,
        "slum": False,
        "slum_status": False,
        "slum_occupants": 0,
        "resicat": 3,
        "household_count": 4,
        "red_count": 1,
        "blue_count": 1,
        "green_count": 1,
        "neutral_count": 1,
        "developer_count": 0,
    }
    cell.update(overrides)
    return cell


def _render_map_markup(
    app_module,
    *,
    cell: dict[str, object],
    layer_name: str,
) -> str:
    captured: list[dict[str, object]] = []

    def capture_html(**kwargs: object) -> None:
        captured.append(dict(kwargs))

    with (
        patch.object(app_module, "patch_grid", return_value=[[cell]]),
        patch.object(
            app_module,
            "patch_grid_style",
            return_value=(
                "grid-template-columns: repeat(1, minmax(0, 1fr)); "
                "grid-template-rows: repeat(1, minmax(0, 1fr));"
            ),
        ),
        patch.object(app_module.solara, "HTML", side_effect=capture_html),
    ):
        app_module._render_patch_map(SimpleNamespace(), layer_name)

    if len(captured) != 1 or "unsafe_innerHTML" not in captured[0]:
        raise AssertionError("Expected one captured Solara HTML map payload.")
    return str(captured[0]["unsafe_innerHTML"])


def _background_rgb(style: str) -> tuple[int, int, int]:
    match = re.search(
        r"(?:background|background-color)\s*:\s*"
        r"(#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?|rgb\([^)]+\)|yellow|gr[ae]y)",
        style,
    )
    if match is None:
        raise AssertionError(f"No parseable background color in style: {style!r}")

    color = match.group(1).lower()
    if color == "yellow":
        return (255, 255, 0)
    if color in {"gray", "grey"}:
        return (128, 128, 128)
    if color.startswith("rgb("):
        channels = tuple(
            int(channel.strip())
            for channel in color.removeprefix("rgb(")[:-1].split(",")
        )
        if len(channels) != 3:
            raise AssertionError(f"Unexpected RGB color: {color!r}")
        return channels  # type: ignore[return-value]

    hexadecimal = color.removeprefix("#")
    if len(hexadecimal) == 3:
        hexadecimal = "".join(channel * 2 for channel in hexadecimal)
    return tuple(int(hexadecimal[index : index + 2], 16) for index in range(0, 6, 2))  # type: ignore[return-value]


def _metric_labels(items) -> tuple[str, ...]:
    labels = []
    for item in items:
        if isinstance(item, dict):
            labels.append(str(item["label"]))
        else:
            labels.append(str(item[0]))
    return tuple(labels)


def _metric_values(items) -> dict[str, str]:
    values = {}
    for item in items:
        if isinstance(item, dict):
            values[str(item["label"])] = str(item["value"])
        else:
            values[str(item[0])] = str(item[1])
    return values


def _representative_cells(cells: list[dict[str, object]]) -> list[dict[str, object]]:
    center = next(cell for cell in cells if cell["x"] == 0 and cell["y"] == 0)
    occupied = next((cell for cell in cells if cell["occupancy"]), center)
    slum = next((cell for cell in cells if cell["slum_status"]), center)
    return [center, occupied, slum]


class _FakeReactive:
    def __init__(self, value) -> None:
        self.initial_value = value
        self.value = value
        self.set_values = []

    def set(self, value) -> None:
        self.value = value
        self.set_values.append(value)


class _ControlledToThread:
    """Provide deterministic barriers at the component's thread boundary."""

    def __init__(self, call_count: int) -> None:
        self.started = [asyncio.Event() for _ in range(call_count)]
        self.release = [asyncio.Event() for _ in range(call_count)]
        self.calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    async def __call__(self, function, /, *args, **kwargs):
        index = len(self.calls)
        if index >= len(self.started):
            raise AssertionError("Playback scheduled an unexpected extra step.")
        self.calls.append((function, args, kwargs))
        self.started[index].set()
        await self.release[index].wait()
        return function(*args, **kwargs)


class _SlumulationPageHarness:
    """Render the Solara component without a server and expose its callbacks."""

    def __init__(
        self,
        app_module,
        *,
        create_state,
        step_state,
        run_steps_state=None,
    ) -> None:
        self.app_module = app_module
        self.create_state = create_state
        self.step_state = step_state
        self.run_steps_state = run_steps_state or self._default_run_steps
        self.stack = ExitStack()
        self.reactives: list[_FakeReactive] = []
        self.memo_slots: list[tuple[tuple[object, ...], object]] = []
        self.task_slots: list[dict[str, object]] = []
        self.buttons: dict[str, dict[str, object]] = {}
        self.selects: dict[str, dict[str, object]] = {}
        self.inputs: dict[str, dict[str, object]] = {}
        self.sliders: dict[str, dict[str, object]] = {}
        self._reactive_cursor = 0
        self._memo_cursor = 0
        self._task_cursor = 0
        self.force_update_mock = None
        self.dashboard_mock = None
        self.playing_reactive: _FakeReactive | None = None

    def __enter__(self):
        module = self.app_module

        self.stack.enter_context(
            patch.object(module.solara, "use_reactive", side_effect=self._use_reactive)
        )
        self.stack.enter_context(
            patch.object(module.solara, "use_memo", side_effect=self._use_memo)
        )
        self.stack.enter_context(
            patch.object(module.solara.lab, "use_task", side_effect=self._use_task)
        )
        for name in ("AppBar", "Sidebar", "Column", "Card", "Row"):
            self.stack.enter_context(
                patch.object(
                    module.solara, name, side_effect=lambda *a, **k: nullcontext()
                )
            )
        for name in ("Style", "HTML", "AppBarTitle", "ToggleButtonsSingle"):
            self.stack.enter_context(
                patch.object(module.solara, name, side_effect=lambda *a, **k: None)
            )
        self.stack.enter_context(
            patch.object(module.solara, "Button", side_effect=self._capture_button)
        )
        self.stack.enter_context(
            patch.object(module.solara, "Select", side_effect=self._capture_select)
        )
        self.stack.enter_context(
            patch.object(module.solara, "InputInt", side_effect=self._capture_input)
        )
        self.stack.enter_context(
            patch.object(module.solara, "SliderInt", side_effect=self._capture_slider)
        )
        self.stack.enter_context(
            patch.object(module.update_counter, "get", return_value=0)
        )
        self.stack.enter_context(
            patch.object(module, "create_app_state", side_effect=self.create_state)
        )
        self.stack.enter_context(
            patch.object(module, "step_app_state", side_effect=self.step_state)
        )
        self.stack.enter_context(
            patch.object(
                module,
                "run_app_steps",
                side_effect=self.run_steps_state,
            )
        )
        self.force_update_mock = self.stack.enter_context(
            patch.object(module, "force_update")
        )
        self.dashboard_mock = self.stack.enter_context(
            patch.object(module, "dashboard_panel")
        )
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stack.close()

    def _use_reactive(self, value):
        index = self._reactive_cursor
        self._reactive_cursor += 1
        if index == len(self.reactives):
            self.reactives.append(_FakeReactive(value))
        return self.reactives[index]

    def _use_memo(self, function, dependencies):
        index = self._memo_cursor
        self._memo_cursor += 1
        dependency_values = tuple(dependencies)
        if index == len(self.memo_slots):
            self.memo_slots.append((dependency_values, function()))
        elif self.memo_slots[index][0] != dependency_values:
            self.memo_slots[index] = (dependency_values, function())
        return self.memo_slots[index][1]

    def _use_task(self, function, *, dependencies, **kwargs) -> None:
        index = self._task_cursor
        self._task_cursor += 1
        task = {
            "function": function,
            "dependencies": tuple(dependencies),
            **kwargs,
        }
        if index == len(self.task_slots):
            self.task_slots.append(task)
        elif self.task_slots[index]["dependencies"] != task["dependencies"]:
            self.task_slots[index] = task

    def _capture_button(self, *, label, on_click, **kwargs) -> None:
        self.buttons[str(label)] = {"on_click": on_click, **kwargs}

    def _capture_select(self, label, *, on_value, **kwargs) -> None:
        self.selects[str(label)] = {"on_value": on_value, **kwargs}

    def _capture_input(self, label, *, on_value, **kwargs) -> None:
        self.inputs[str(label)] = {"on_value": on_value, **kwargs}

    def _capture_slider(self, label, *, on_value, **kwargs) -> None:
        self.sliders[str(label)] = {"on_value": on_value, **kwargs}

    def _default_run_steps(self, state, steps):
        for _ in range(steps):
            if state.stopped:
                break
            self.step_state(state)
        return state

    def render(self) -> None:
        self._reactive_cursor = 0
        self._memo_cursor = 0
        self._task_cursor = 0
        self.buttons = {}
        self.selects = {}
        self.inputs = {}
        self.sliders = {}
        self.app_module.page.f()

    def click(self, label: str) -> None:
        before = [reactive.value for reactive in self.reactives]
        callback = self.buttons[label]["on_click"]
        callback()
        if label == "Run":
            changed_to_true = [
                reactive
                for reactive, prior_value in zip(self.reactives, before, strict=True)
                if reactive.initial_value is False
                and prior_value is False
                and reactive.value is True
            ]
            if len(changed_to_true) == 1:
                self.playing_reactive = changed_to_true[0]

    def set_select(self, label: str, value: str) -> None:
        callback = self.selects[label]["on_value"]
        callback(value)

    def set_input(self, label: str, value: int) -> None:
        callback = self.inputs[label]["on_value"]
        callback(value)

    def set_run_steps(self, value: int) -> None:
        self.sliders["Run steps"]["on_value"](value)

    async def run_task(self, task=None, *, to_thread=None) -> None:
        if len(self.task_slots) != 1:
            raise AssertionError(
                f"Expected one playback task, found {len(self.task_slots)}."
            )
        task = task or self.task_slots[0]["function"]

        async def no_wait(*args, **kwargs) -> None:
            return None

        async def immediate_to_thread(function, /, *args, **kwargs):
            return function(*args, **kwargs)

        real_sleep = asyncio.sleep
        with (
            patch.object(self.app_module.asyncio, "sleep", new=no_wait),
            patch.object(
                self.app_module.asyncio,
                "to_thread",
                new=to_thread or immediate_to_thread,
            ),
        ):
            controller = asyncio.create_task(task())
            try:
                for _ in range(1000):
                    await real_sleep(0)
                    if self.playing_reactive is None:
                        raise AssertionError("Run did not activate playback state.")
                    if not self.playing_reactive.value:
                        await real_sleep(0)
                        return
                    if controller.done():
                        await controller
                        return
                raise AssertionError("Playback controller did not become idle.")
            finally:
                if not controller.done():
                    controller.cancel()
                await asyncio.gather(controller, return_exceptions=True)


class SlumulationAppHelperTests(unittest.TestCase):
    def test_app_module_imports_without_starting_solara(self) -> None:
        app = importlib.import_module("slumulation.app")

        self.assertTrue(hasattr(app, "create_app_state"))
        self.assertFalse(hasattr(app, "server"))
        self.assertFalse(hasattr(app, "triptych_panel"))

    def test_experiment_options_match_selected_bounded_surface(self) -> None:
        api = _app_api()
        options = api.experiment_options()

        self.assertEqual(options, EXPECTED_EXPERIMENT_OPTIONS)
        self.assertEqual(api.DEFAULT_EXPERIMENT_NAME, "Typical Run")

    def test_experiment_specs_and_parameter_options_are_registry_backed(self) -> None:
        api = _app_api()

        for experiment_name, expected_count in EXPECTED_PARAMETER_COUNTS.items():
            spec = api.experiment_spec_for_name(experiment_name)
            registry_spec = constants.SELECTED_EXPERIMENT_REGISTRY[experiment_name]
            self.assertIs(spec, registry_spec)

            parameter_options = api.parameter_condition_options(experiment_name)
            self.assertEqual(len(parameter_options), expected_count)
            self.assertEqual(
                _option_labels(parameter_options),
                tuple(
                    combination.label
                    for combination in registry_spec.parameter_combinations
                ),
            )

            for index, expected_combination in enumerate(
                registry_spec.parameter_combinations
            ):
                self.assertEqual(
                    _parameter_values(
                        api.parameter_combination_for_index(experiment_name, index)
                    ),
                    dict(expected_combination.parameter_values),
                )

        with self.assertRaisesRegex(ValueError, "Unknown.*Slumulation.*experiment"):
            api.experiment_spec_for_name("Urbanization")

    def test_composite_is_default_and_prior_diagnostic_layers_remain(self) -> None:
        api = _app_api()
        option_names = _option_names(api.layer_options())
        constant_option_names = _option_names(api.LAYER_OPTIONS)

        self.assertEqual(api.DEFAULT_LAYER_NAME, "composite")
        self.assertEqual(option_names, constant_option_names)
        self.assertEqual(option_names, EXPECTED_LAYER_NAMES)
        self.assertEqual(option_names[0], "composite")
        for layer_name in PRIOR_DIAGNOSTIC_LAYER_NAMES:
            self.assertIn(layer_name, option_names)
        self.assertIn("developers", option_names)

    def test_patch_grid_describes_default_world_in_deterministic_order(self) -> None:
        api = _app_api()
        state = api.create_app_state()
        grid = api.patch_grid(state.world)
        cells = _flatten_grid(grid)

        self.assertEqual(len(grid), 51)
        self.assertTrue(all(len(row) == 51 for row in grid))
        self.assertEqual(len(cells), 2601)
        self.assertEqual((grid[0][0]["x"], grid[0][0]["y"]), (-25, 25))
        self.assertEqual((grid[0][-1]["x"], grid[0][-1]["y"]), (25, 25))
        self.assertEqual((grid[-1][0]["x"], grid[-1][0]["y"]), (-25, -25))
        self.assertEqual((grid[-1][-1]["x"], grid[-1][-1]["y"]), (25, -25))
        self.assertEqual(
            [(cell["x"], cell["y"]) for cell in grid[25][23:28]],
            [(-2, 0), (-1, 0), (0, 0), (1, 0), (2, 0)],
        )

        expected_fields = {
            "x",
            "y",
            "ward",
            "rent",
            "occupied",
            "occupancy",
            "num_occupants",
            "slum_status",
            "slum_occupants",
            "resicat",
            "household_count",
            "red_count",
            "blue_count",
            "green_count",
            "neutral_count",
            "developer_count",
        }
        self.assertTrue(expected_fields.issubset(cells[0]))
        self.assertTrue(all(1 <= int(cell["ward"]) <= 9 for cell in cells))

    def test_patch_grid_counts_classes_and_developers_without_losing_colocation(
        self,
    ) -> None:
        api = _app_api()
        world = build_empty_world()
        world.households.extend(
            [
                HouseholdState(x=0, y=0, income_class=None),
                HouseholdState(x=0, y=0, income_class="green"),
                HouseholdState(x=0, y=0, income_class="red"),
                HouseholdState(x=0, y=0, income_class="blue"),
                HouseholdState(x=0, y=0, income_class="red"),
                HouseholdState(x=1, y=0, income_class=None),
            ]
        )
        world.developers.extend(
            [
                DeveloperState(x=0, y=0),
                DeveloperState(x=0, y=0),
                DeveloperState(x=1, y=0),
            ]
        )

        first_grid = api.patch_grid(world)
        colocated = _cell_at(first_grid, 0, 0)
        neighbor = _cell_at(first_grid, 1, 0)

        self.assertEqual(
            {
                "household_count": colocated["household_count"],
                "red_count": colocated["red_count"],
                "blue_count": colocated["blue_count"],
                "green_count": colocated["green_count"],
                "neutral_count": colocated["neutral_count"],
                "developer_count": colocated["developer_count"],
            },
            {
                "household_count": 5,
                "red_count": 2,
                "blue_count": 1,
                "green_count": 1,
                "neutral_count": 1,
                "developer_count": 2,
            },
        )
        self.assertEqual(neighbor["neutral_count"], 1)
        self.assertEqual(neighbor["developer_count"], 1)

        world.households.reverse()
        world.developers.reverse()
        self.assertEqual(api.patch_grid(world), first_grid)

    def test_patch_grid_style_uses_equal_columns_and_rows(self) -> None:
        api = _app_api()
        style = api.patch_grid_style(api.create_app_state().world)

        self.assertIn("grid-template-columns: repeat(51, minmax(0, 1fr));", style)
        self.assertIn("grid-template-rows: repeat(51, minmax(0, 1fr));", style)

    def test_cell_style_is_deterministic_by_layer_and_rejects_unknown_layers(
        self,
    ) -> None:
        api = _app_api()
        cells = _flatten_grid(api.patch_grid(api.create_app_state().world))

        for layer_name in EXPECTED_LAYER_NAMES:
            for cell in _representative_cells(cells):
                self.assertEqual(
                    api.cell_style(cell, layer_name),
                    api.cell_style(dict(cell), layer_name),
                )

        with self.assertRaisesRegex(ValueError, "Unknown.*layer"):
            api.cell_style(cells[0], "validation_claim")

    def test_composite_excludes_developers_and_developer_layer_shows_presence(
        self,
    ) -> None:
        api = _app_api()
        without_developer = _sample_cell(developer_count=0)
        with_developer = _sample_cell(developer_count=3)

        self.assertEqual(
            api.cell_style(without_developer, "composite"),
            api.cell_style(with_developer, "composite"),
        )
        composite_markup = _render_map_markup(
            api.module,
            cell=with_developer,
            layer_name="composite",
        )
        empty_developer_markup = _render_map_markup(
            api.module,
            cell=without_developer,
            layer_name="developers",
        )
        developer_markup = _render_map_markup(
            api.module,
            cell=with_developer,
            layer_name="developers",
        )

        self.assertNotIn("slumulation-developer-marker", composite_markup)
        self.assertNotIn("slumulation-developer-marker", empty_developer_markup)
        self.assertIn("slumulation-developer-marker", developer_markup)
        self.assertIn('data-count="3"', developer_markup)

    def test_composite_background_is_yellow_with_grey_slum_override(self) -> None:
        api = _app_api()
        rent_rgb = _background_rgb(
            api.cell_style(_sample_cell(rent=320.0, slum=False), "composite")
        )
        low_rent_slum_style = api.cell_style(
            _sample_cell(rent=10.0, slum=True, slum_status=True),
            "composite",
        )
        high_rent_slum_style = api.cell_style(
            _sample_cell(rent=1_200.0, slum=True, slum_status=True),
            "composite",
        )
        slum_rgb = _background_rgb(low_rent_slum_style)

        self.assertGreaterEqual(rent_rgb[0], 180)
        self.assertGreaterEqual(rent_rgb[1], 140)
        self.assertLessEqual(rent_rgb[2], 120)
        self.assertEqual(low_rent_slum_style, high_rent_slum_style)
        self.assertLessEqual(max(slum_rgb) - min(slum_rgb), 24)

    def test_composite_markup_keeps_colocated_rgb_overlays_in_source_order(
        self,
    ) -> None:
        api = _app_api()
        markup = _render_map_markup(
            api.module,
            cell=_sample_cell(
                household_count=10,
                red_count=3,
                blue_count=2,
                green_count=1,
                neutral_count=4,
            ),
            layer_name="composite",
        )

        positions = []
        for income_class in ("red", "blue", "green", "neutral"):
            marker = re.search(
                rf'<[^>]+(?:class|data-income-class)="[^"]*'
                rf'{income_class}[^"]*"[^>]*>',
                markup,
            )
            self.assertIsNotNone(
                marker,
                f"Composite markup lost the {income_class} household overlay.",
            )
            positions.append(marker.start())
        self.assertEqual(positions, sorted(positions))

        for label in (
            "lower/red: 3",
            "middle/blue: 2",
            "higher/green: 1",
            "neutral/unclassified: 4",
        ):
            self.assertIn(label, markup)
        for income_class, count in (
            ("red", 3),
            ("blue", 2),
            ("green", 1),
            ("neutral", 4),
        ):
            self.assertRegex(
                markup,
                rf'data-income-class="{income_class}" data-count="{count}"',
            )
        self.assertIn('data-segment-count="4"', markup)

    def test_map_markup_keeps_stable_capture_selectors_and_cell_labels(self) -> None:
        api = _app_api()
        markup = _render_map_markup(
            api.module,
            cell=_sample_cell(),
            layer_name="composite",
        )

        self.assertIn('class="slumulation-map', markup)
        self.assertIn('data-testid="slumulation-composite-map"', markup)
        self.assertIn('data-layer="composite"', markup)
        self.assertIn('data-x="0" data-y="0"', markup)
        self.assertIn('class="slumulation-cell', markup)
        for label in (
            "Coordinates: (0, 0)",
            "rent: 320.000",
            "lower/red: 1",
            "middle/blue: 1",
            "higher/green: 1",
            "neutral/unclassified: 1",
            "occupancy: 4",
            "developers: 0",
        ):
            self.assertIn(label, markup)

    def test_page_retains_controls_and_ui_avoids_evidence_claim_language(
        self,
    ) -> None:
        api = _app_api()
        page_source = inspect.getsource(api.module.page)
        for label in (
            "Experiment",
            "Parameter condition",
            "Seed",
            "Patch layer",
            "Run steps",
            "Reset",
            "Step",
            "Run",
            "Pause",
        ):
            self.assertIn(label, page_source)
        self.assertIn("use_task", page_source)

        ui_source = "\n".join(
            inspect.getsource(component)
            for component in (
                api.module._render_patch_map,
                api.module._patch_map_html,
                api.module._cell_tooltip,
                api.module._household_marker_html,
                api.module._developer_marker_html,
                api.module._legend_html,
                api.module.map_panel,
                api.module.run_state_panel,
                api.module.metrics_panel,
                api.module.parameter_panel,
                api.module.dashboard_panel,
                api.module.page,
            )
        ).lower()
        markup = _render_map_markup(
            api.module,
            cell=_sample_cell(),
            layer_name="composite",
        ).lower()
        for forbidden in (
            "validation",
            "replication",
            "paper claim",
            "paper-claim",
            "netlogo",
            "comparison",
        ):
            self.assertNotIn(forbidden, ui_source)
            self.assertNotIn(forbidden, markup)

    def test_step_advances_exactly_once_while_paused(self) -> None:
        api = _app_api()
        state = SimpleNamespace(stopped=False, emitted_step=0)
        calls = []

        def create_state(*args, **kwargs):
            return state

        def step_state(target):
            calls.append(target)
            target.emitted_step += 1
            return target

        with _SlumulationPageHarness(
            api.module,
            create_state=create_state,
            step_state=step_state,
        ) as harness:
            harness.render()
            self.assertIn("Run", harness.buttons)
            self.assertFalse(harness.buttons["Step"].get("disabled", False))

            harness.click("Step")

            self.assertEqual(calls, [state])
            self.assertEqual(state.emitted_step, 1)
            self.assertEqual(harness.force_update_mock.call_count, 1)

    def test_run_continues_across_intervals_with_one_controller(self) -> None:
        api = _app_api()
        state = SimpleNamespace(stopped=False, emitted_step=0)
        calls = []
        harness = None

        def create_state(*args, **kwargs):
            return state

        def step_state(target):
            calls.append(target)
            target.emitted_step += 1
            if len(calls) == 6:
                harness.click("Pause")
            return target

        with _SlumulationPageHarness(
            api.module,
            create_state=create_state,
            step_state=step_state,
        ) as active_harness:
            harness = active_harness
            harness.render()
            harness.set_run_steps(2)
            harness.click("Run")
            harness.render()

            self.assertIn("Pause", harness.buttons)
            self.assertEqual(len(harness.task_slots), 1)
            asyncio.run(harness.run_task())

            self.assertEqual(len(calls), 6)
            self.assertEqual(state.emitted_step, 6)
            harness.render()
            self.assertIn("Run", harness.buttons)

    def test_pause_prevents_further_steps(self) -> None:
        api = _app_api()
        state = SimpleNamespace(stopped=False, emitted_step=0)
        calls = []

        def create_state(*args, **kwargs):
            return state

        def step_state(target):
            calls.append(target)
            target.emitted_step += 1
            return target

        with _SlumulationPageHarness(
            api.module,
            create_state=create_state,
            step_state=step_state,
        ) as harness:
            harness.render()
            harness.click("Run")
            harness.render()
            harness.click("Pause")

            asyncio.run(harness.run_task())

            self.assertEqual(calls, [])
            self.assertEqual(state.emitted_step, 0)
            harness.render()
            self.assertIn("Run", harness.buttons)

    def test_pause_during_in_flight_step_prevents_the_next_step(self) -> None:
        api = _app_api()
        state = SimpleNamespace(stopped=False, emitted_step=0)
        calls = []

        def create_state(*args, **kwargs):
            return state

        def step_state(target):
            calls.append(target)
            target.emitted_step += 1
            if len(calls) >= 5:
                target.stopped = True
            return target

        with _SlumulationPageHarness(
            api.module,
            create_state=create_state,
            step_state=step_state,
        ) as harness:
            harness.render()
            harness.set_run_steps(3)
            harness.click("Run")
            harness.render()
            run_task = harness.task_slots[0]["function"]

            async def exercise_interleaving() -> None:
                gate = _ControlledToThread(1)
                runner = asyncio.create_task(harness.run_task(run_task, to_thread=gate))
                await asyncio.wait_for(gate.started[0].wait(), timeout=1)
                harness.click("Pause")
                gate.release[0].set()
                await asyncio.wait_for(runner, timeout=1)
                self.assertEqual(len(gate.calls), 1)

            asyncio.run(exercise_interleaving())

            self.assertEqual(calls, [state])
            self.assertEqual(state.emitted_step, 1)

    def test_step_stays_guarded_until_paused_worker_returns(self) -> None:
        api = _app_api()
        state = SimpleNamespace(stopped=False, emitted_step=0)
        worker_entered = threading.Event()
        worker_release = threading.Event()
        worker_returned = threading.Event()
        worker_mutations = []
        manual_step_calls = []

        def create_state(*args, **kwargs):
            return state

        def step_state(target):
            manual_step_calls.append(target)
            target.emitted_step += 1
            return target

        def blocking_run_step(target, steps):
            worker_entered.set()
            try:
                if not worker_release.wait(timeout=2):
                    raise AssertionError("Timed out waiting to release Run worker.")
                worker_mutations.append(target)
                target.emitted_step += 1
                return target
            finally:
                worker_returned.set()

        with _SlumulationPageHarness(
            api.module,
            create_state=create_state,
            step_state=step_state,
            run_steps_state=blocking_run_step,
        ) as harness:
            harness.render()
            controller_function = harness.task_slots[0]["function"]

            async def wait_for_thread_event(event: threading.Event) -> None:
                deadline = asyncio.get_running_loop().time() + 1
                while not event.is_set():
                    if asyncio.get_running_loop().time() >= deadline:
                        raise AssertionError("Timed out waiting for Run worker.")
                    await asyncio.sleep(0.001)

            async def exercise_step_guard() -> None:
                controller_task = None
                results = []
                try:
                    with patch.object(api.module, "DEFAULT_PLAY_INTERVAL_MS", 0):
                        controller_task = asyncio.create_task(controller_function())
                        await asyncio.sleep(0)

                        harness.click("Run")
                        harness.render()
                        await wait_for_thread_event(worker_entered)

                        harness.click("Pause")
                        harness.render()
                        self.assertTrue(harness.buttons["Step"].get("disabled", False))
                        blocked_step_callback = harness.buttons["Step"]["on_click"]
                        blocked_step_callback()
                        self.assertEqual(manual_step_calls, [])

                        worker_release.set()
                        await wait_for_thread_event(worker_returned)
                        for _ in range(5):
                            await asyncio.sleep(0)

                        harness.render()
                        self.assertFalse(harness.buttons["Step"].get("disabled", False))
                        harness.click("Step")
                finally:
                    worker_release.set()
                    if controller_task is not None and not controller_task.done():
                        controller_task.cancel()
                    if controller_task is not None:
                        results = list(
                            await asyncio.gather(
                                controller_task,
                                return_exceptions=True,
                            )
                        )

                unexpected_errors = [
                    result
                    for result in results
                    if isinstance(result, BaseException)
                    and not isinstance(result, asyncio.CancelledError)
                ]
                self.assertEqual(unexpected_errors, [])

            asyncio.run(exercise_step_guard())

            self.assertEqual(worker_mutations, [state])
            self.assertEqual(manual_step_calls, [state])
            self.assertEqual(state.emitted_step, 2)

    def test_reset_during_in_flight_step_cannot_mutate_or_repaint_replacement(
        self,
    ) -> None:
        api = _app_api()
        states = []
        calls = []

        def create_state(*args, **kwargs):
            state = SimpleNamespace(stopped=False, emitted_step=0, build=len(states))
            states.append(state)
            return state

        def step_state(target):
            calls.append(target)
            target.emitted_step += 1
            if len(calls) >= 5:
                target.stopped = True
            return target

        with _SlumulationPageHarness(
            api.module,
            create_state=create_state,
            step_state=step_state,
        ) as harness:
            harness.render()
            harness.set_run_steps(3)
            harness.click("Run")
            harness.render()
            stale_task = harness.task_slots[0]["function"]

            async def exercise_stale_reset() -> None:
                gate = _ControlledToThread(1)
                runner = asyncio.create_task(
                    harness.run_task(stale_task, to_thread=gate)
                )
                await asyncio.wait_for(gate.started[0].wait(), timeout=1)

                old_state = states[0]
                harness.click("Reset")
                replacement_state = states[-1]
                repaint_snapshot = [
                    list(reactive.set_values) for reactive in harness.reactives
                ]
                force_update_count = harness.force_update_mock.call_count

                gate.release[0].set()
                await asyncio.wait_for(runner, timeout=1)

                self.assertEqual(calls, [old_state])
                self.assertEqual(old_state.emitted_step, 1)
                self.assertEqual(replacement_state.emitted_step, 0)
                self.assertEqual(
                    [list(reactive.set_values) for reactive in harness.reactives],
                    repaint_snapshot,
                )
                self.assertEqual(
                    harness.force_update_mock.call_count,
                    force_update_count,
                )

            asyncio.run(exercise_stale_reset())

    def test_rapid_run_pause_run_serializes_threaded_model_steps(self) -> None:
        api = _app_api()
        state = SimpleNamespace(stopped=False, emitted_step=0)
        calls = []
        entered = [threading.Event(), threading.Event()]
        release = [threading.Event(), threading.Event()]
        returned = [threading.Event(), threading.Event()]
        active_calls = 0
        max_concurrent_calls = 0
        counter_lock = threading.Lock()

        def create_state(*args, **kwargs):
            return state

        def step_state(target):
            target.emitted_step += 1
            return target

        def blocking_run_steps(target, steps):
            nonlocal active_calls, max_concurrent_calls
            with counter_lock:
                index = len(calls)
                if index >= len(entered):
                    raise AssertionError("A stale controller scheduled an extra step.")
                calls.append(target)
                active_calls += 1
                max_concurrent_calls = max(max_concurrent_calls, active_calls)
            entered[index].set()
            try:
                if not release[index].wait(timeout=2):
                    raise AssertionError("Timed out waiting to release model step.")
                step_state(target)
                if index == 1:
                    target.stopped = True
                return target
            finally:
                with counter_lock:
                    active_calls -= 1
                returned[index].set()

        with _SlumulationPageHarness(
            api.module,
            create_state=create_state,
            step_state=step_state,
            run_steps_state=blocking_run_steps,
        ) as harness:
            harness.render()
            harness.set_run_steps(3)
            controller_function = harness.task_slots[0]["function"]

            async def wait_for_thread_event(event: threading.Event) -> None:
                deadline = asyncio.get_running_loop().time() + 1
                while not event.is_set():
                    if asyncio.get_running_loop().time() >= deadline:
                        raise AssertionError(
                            "Timed out waiting for threaded model step."
                        )
                    await asyncio.sleep(0.001)

            async def exercise_generations() -> None:
                baseline_tasks = set(asyncio.all_tasks())
                controller_task = None
                results = []
                try:
                    with patch.object(api.module, "DEFAULT_PLAY_INTERVAL_MS", 0):
                        controller_task = asyncio.create_task(controller_function())
                        await asyncio.sleep(0)

                        harness.click("Run")
                        harness.render()
                        await wait_for_thread_event(entered[0])

                        harness.click("Pause")
                        harness.render()
                        harness.click("Run")
                        harness.render()

                        await asyncio.sleep(0.02)
                        self.assertFalse(entered[1].is_set())
                        self.assertEqual(max_concurrent_calls, 1)

                        repaint_before_stale_release = [
                            list(reactive.set_values) for reactive in harness.reactives
                        ]
                        force_update_before_stale_release = (
                            harness.force_update_mock.call_count
                        )

                        release[0].set()
                        await wait_for_thread_event(returned[0])
                        await wait_for_thread_event(entered[1])

                        self.assertEqual(max_concurrent_calls, 1)
                        self.assertEqual(
                            [
                                list(reactive.set_values)
                                for reactive in harness.reactives
                            ],
                            repaint_before_stale_release,
                        )
                        self.assertEqual(
                            harness.force_update_mock.call_count,
                            force_update_before_stale_release,
                        )

                        release[1].set()
                        await wait_for_thread_event(returned[1])
                        await asyncio.sleep(0)
                finally:
                    for event in release:
                        event.set()
                    if controller_task is not None and not controller_task.done():
                        controller_task.cancel()
                    if controller_task is not None:
                        results = list(
                            await asyncio.gather(
                                controller_task,
                                return_exceptions=True,
                            )
                        )
                    created_tasks = {
                        task
                        for task in asyncio.all_tasks()
                        if task not in baseline_tasks
                        and task is not asyncio.current_task()
                        and not task.done()
                    }
                    for task in created_tasks:
                        task.cancel()
                    if created_tasks:
                        await asyncio.gather(*created_tasks, return_exceptions=True)

                unexpected_errors = [
                    result
                    for result in results
                    if isinstance(result, BaseException)
                    and not isinstance(result, asyncio.CancelledError)
                ]
                self.assertEqual(unexpected_errors, [])
                self.assertFalse(
                    [
                        task
                        for task in asyncio.all_tasks()
                        if task not in baseline_tasks
                        and task is not asyncio.current_task()
                        and not task.done()
                    ]
                )

            asyncio.run(exercise_generations())

            self.assertEqual(calls, [state, state])
            self.assertEqual(state.emitted_step, 2)
            self.assertEqual(max_concurrent_calls, 1)

    def test_reset_stops_playback_and_rebuilds_initial_state(self) -> None:
        api = _app_api()
        states = []

        def create_state(*args, **kwargs):
            state = SimpleNamespace(stopped=False, emitted_step=0, build=len(states))
            states.append(state)
            return state

        def step_state(target):
            target.emitted_step += 1
            return target

        with _SlumulationPageHarness(
            api.module,
            create_state=create_state,
            step_state=step_state,
        ) as harness:
            harness.render()
            harness.click("Run")
            harness.render()
            self.assertIn("Pause", harness.buttons)

            harness.click("Reset")
            harness.render()

            self.assertEqual(len(states), 2)
            self.assertIn("Run", harness.buttons)
            self.assertIs(harness.dashboard_mock.call_args.args[0], states[-1])

    def test_experiment_condition_and_seed_changes_stop_playback(self) -> None:
        api = _app_api()

        def exercise_change(change_callback) -> None:
            states = []

            def create_state(*args, **kwargs):
                state = SimpleNamespace(stopped=False, emitted_step=0)
                states.append(state)
                return state

            def step_state(target):
                target.emitted_step += 1
                return target

            with _SlumulationPageHarness(
                api.module,
                create_state=create_state,
                step_state=step_state,
            ) as harness:
                harness.render()
                change_callback(harness, before_run=True)
                harness.render()
                harness.click("Run")
                harness.render()
                self.assertIn("Pause", harness.buttons)

                change_callback(harness, before_run=False)
                harness.render()

                self.assertIn("Run", harness.buttons)
                self.assertGreaterEqual(len(states), 2)

        with self.subTest(control="experiment"):
            exercise_change(
                lambda harness, before_run: (
                    None
                    if before_run
                    else harness.set_select("Experiment", "Population Growth Rate")
                )
            )

        with self.subTest(control="seed"):
            exercise_change(
                lambda harness, before_run: (
                    None if before_run else harness.set_input("Seed", 20260710)
                )
            )

        def change_condition(harness, before_run: bool) -> None:
            if before_run:
                harness.set_select("Experiment", "Population Growth Rate")
                return
            labels = harness.selects["Parameter condition"]["values"]
            selected = harness.selects["Parameter condition"]["value"]
            new_label = next(label for label in labels if label != selected)
            harness.set_select("Parameter condition", new_label)

        with self.subTest(control="parameter condition"):
            exercise_change(change_condition)

    def test_source_stop_condition_halts_playback(self) -> None:
        api = _app_api()
        state = SimpleNamespace(stopped=False, emitted_step=0)
        calls = []

        def create_state(*args, **kwargs):
            return state

        def step_state(target):
            calls.append(target)
            target.emitted_step += 1
            target.stopped = True
            return target

        with _SlumulationPageHarness(
            api.module,
            create_state=create_state,
            step_state=step_state,
        ) as harness:
            harness.render()
            harness.click("Run")
            harness.render()
            asyncio.run(harness.run_task())

            self.assertEqual(calls, [state])
            harness.render()
            self.assertIn("Run", harness.buttons)
            self.assertTrue(harness.buttons["Run"].get("disabled", False))

    def test_gui_controlled_steps_match_direct_existing_steps(self) -> None:
        api = _app_api()
        direct_state = api.create_app_state(seed=api.DEFAULT_SEED)
        actual_create_state = api.create_app_state
        actual_step_state = api.step_app_state
        gui_states = []
        step_count = 2
        harness = None

        def create_state(*args, **kwargs):
            state = actual_create_state(*args, **kwargs)
            gui_states.append(state)
            return state

        def gui_step_state(target):
            actual_step_state(target)
            if target.emitted_step == step_count:
                harness.click("Pause")
            return target

        with _SlumulationPageHarness(
            api.module,
            create_state=create_state,
            step_state=gui_step_state,
        ) as active_harness:
            harness = active_harness
            harness.render()
            harness.click("Run")
            harness.render()
            asyncio.run(harness.run_task())

        for _ in range(step_count):
            actual_step_state(direct_state)

        gui_state = gui_states[0]
        self.assertEqual(gui_state.emitted_step, direct_state.emitted_step)
        self.assertEqual(gui_state.world.time, direct_state.world.time)
        self.assertEqual(gui_state.rng.getstate(), direct_state.rng.getstate())
        self.assertEqual(
            api.patch_grid(gui_state.world), api.patch_grid(direct_state.world)
        )
        self.assertEqual(
            api.metric_items(
                gui_state.world,
                gui_state.emitted_step,
                gui_state.stopped,
                gui_state.stop_reason,
            ),
            api.metric_items(
                direct_state.world,
                direct_state.emitted_step,
                direct_state.stopped,
                direct_state.stop_reason,
            ),
        )

        for component_name in (
            "map_panel",
            "run_state_panel",
            "metrics_panel",
            "dashboard_panel",
        ):
            with self.subTest(component=component_name):
                component = getattr(api.module, component_name)
                self.assertIn(
                    "render_revision", inspect.signature(component.f).parameters
                )

        dashboard_source = inspect.getsource(api.module.dashboard_panel)
        for call in (
            "map_panel(state, layer_name, render_revision)",
            "run_state_panel(state, render_revision)",
            "metrics_panel(state, render_revision)",
        ):
            self.assertIn(call, dashboard_source)

    def test_metric_items_show_state_and_key_inspection_metrics(self) -> None:
        api = _app_api()
        state = api.create_app_state()
        items = api.metric_items(
            state.world,
            emitted_step=7,
            stopped=True,
            stop_reason="tick did not advance",
        )
        labels = _metric_labels(items)
        values = _metric_values(items)

        self.assertIn("Current Time", labels)
        self.assertIn("Emitted Step", labels)
        self.assertIn("Run State", labels)
        self.assertIn("Stop Status", labels)
        self.assertEqual(values["Current Time"], str(state.world.time))
        self.assertEqual(values["Emitted Step"], "7")
        self.assertEqual(values["Run State"], "Stopped")
        self.assertIn("tick did not advance", values["Stop Status"])
        for label in (
            "Population",
            "Slum Population",
            "Slum Population Percent",
            "Number Of Slums",
            "Average Income",
            "Highest Rent",
            "Lowest Rent",
            "Number Searching",
        ):
            self.assertIn(label, labels)

        joined_labels = " ".join(labels).lower()
        self.assertNotIn("validation", joined_labels)
        self.assertNotIn("paper", joined_labels)
        self.assertNotIn("netlogo", joined_labels)
        self.assertNotIn("replication", joined_labels)

    def test_format_metric_value_keeps_display_bounded(self) -> None:
        api = _app_api()

        self.assertEqual(api.format_metric_value(7), "7")
        self.assertEqual(api.format_metric_value(True), "True")
        self.assertEqual(api.format_metric_value(None), "n/a")
        self.assertEqual(api.format_metric_value(1 / 3), "0.333")

    def test_step_app_state_uses_stub_step_result_accounting(self) -> None:
        api = _app_api()
        state = api.create_app_state()
        before_step = state.emitted_step
        before_time = state.world.time
        calls = []

        def stub_step_fn(world, parameters, rng):
            calls.append((world, parameters, rng))
            world.time += 1
            return SlumulateStepResult(stopped=False, tick_advanced=True)

        next_state = _call_with_supported_keywords(
            api.step_app_state,
            state=state,
            step_fn=stub_step_fn,
        )

        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][0], state.world)
        self.assertEqual(next_state.emitted_step, before_step + 1)
        self.assertFalse(next_state.stopped)
        self.assertEqual(next_state.world.time, before_time + 1)

    def test_step_app_state_sets_stop_state_when_tick_does_not_advance(self) -> None:
        api = _app_api()
        state = api.create_app_state()
        before_step = state.emitted_step

        def stopping_step_fn(world, parameters, rng):
            return SimpleNamespace(stopped=True, tick_advanced=False)

        stopped_state = _call_with_supported_keywords(
            api.step_app_state,
            state=state,
            step_fn=stopping_step_fn,
        )

        self.assertEqual(stopped_state.emitted_step, before_step)
        self.assertTrue(stopped_state.stopped)
        self.assertIn("tick", stopped_state.stop_reason.lower())

    def test_run_app_steps_uses_stub_step_fn_and_rejects_negative_steps(self) -> None:
        api = _app_api()
        state = api.create_app_state()
        before_step = state.emitted_step
        results = [
            SlumulateStepResult(stopped=False, tick_advanced=True),
            SlumulateStepResult(stopped=False, tick_advanced=False),
            SlumulateStepResult(stopped=False, tick_advanced=True),
        ]

        def stub_step_fn(world, parameters, rng):
            return results.pop(0)

        final_state = _call_with_supported_keywords(
            api.run_app_steps,
            state=state,
            steps=3,
            step_fn=stub_step_fn,
        )

        self.assertEqual(final_state.emitted_step, before_step + 1)
        self.assertTrue(final_state.stopped)
        self.assertEqual(len(results), 1)

        with self.assertRaisesRegex(ValueError, "steps must be non-negative"):
            _call_with_supported_keywords(
                api.run_app_steps,
                state=state,
                steps=-1,
                step_fn=stub_step_fn,
            )


if __name__ == "__main__":
    unittest.main()
