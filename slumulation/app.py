from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from random import Random
from typing import Any

import solara
from mesa.visualization.solara_viz import force_update, update_counter

from slumulation.constants import (
    METRIC_CROSSWALK_BY_NETLOGO_NAME,
    PARAMETER_FIELD_ORDER,
    SELECTED_EXPERIMENT_REGISTRY,
    SELECTED_EXPERIMENTS,
    SOURCE_EMITTED_METRIC_NAMES,
)
from slumulation.dynamics import slumulate_step
from slumulation.setup import (
    SetupParameters,
    load_setup_parameters,
    setup_initial_world,
)
from slumulation.state import Coordinate, PatchState, WorldState

DEFAULT_EXPERIMENT_NAME = "Typical Run"
DEFAULT_SEED = 20260709
DEFAULT_LAYER_NAME = "composite"
DEFAULT_RUN_STEPS = 1
DEFAULT_PLAY_INTERVAL_MS = 250
LAYER_OPTIONS: tuple[dict[str, str], ...] = (
    {"name": "composite", "label": "Composite"},
    {"name": "slum_status", "label": "Slum status"},
    {"name": "rent", "label": "Rent"},
    {"name": "ward", "label": "Ward"},
    {"name": "occupancy", "label": "Occupancy"},
    {"name": "resicat", "label": "Residential category"},
    {"name": "developers", "label": "Developers"},
)

_LAYER_LABELS = {option["name"]: option["label"] for option in LAYER_OPTIONS}
_INCOME_CLASS_ORDER = ("red", "blue", "green", "neutral")
_INCOME_CLASS_LABELS = {
    "red": "Lower income",
    "blue": "Middle income",
    "green": "Higher income",
    "neutral": "Neutral / unclassified",
}
_INCOME_CLASS_COLORS = {
    "red": "#dc2626",
    "blue": "#2563eb",
    "green": "#16a34a",
    "neutral": "#f8fafc",
}
_COMPOSITE_SLUM_COLOR = "#6b7280"
_DEVELOPER_COLOR = "#111827"
_RESICAT_COLORS = {
    0: "#f8fafc",
    1: "#c7f0d8",
    2: "#b9dcff",
    3: "#ffc9b8",
    4: "#7f1d1d",
}
_WARD_COLORS = {
    1: "#e5e7eb",
    2: "#bae6fd",
    3: "#bbf7d0",
    4: "#fde68a",
    5: "#fecaca",
    6: "#ddd6fe",
    7: "#fed7aa",
    8: "#a7f3d0",
    9: "#bfdbfe",
}

SLUMULATION_CSS = """
.slumulation-shell {
    width: 100%;
    padding: 8px 8px 18px;
    color: #172033;
}

div:has(> b > a[href="https://solara.dev"]) {
    position: static !important;
    right: auto !important;
    bottom: auto !important;
    box-sizing: border-box;
    display: block;
    width: 100%;
    padding: 10px !important;
    text-align: right;
}

.slumulation-sidebar-card {
    border: 1px solid #d7dde5;
    box-shadow: none !important;
    background: #f8fafc;
}

.slumulation-card .v-card__title,
.slumulation-sidebar-card .v-card__title {
    padding-bottom: 0;
    font-size: 0.98rem;
    line-height: 1.25;
    color: #25364d;
}

.slumulation-card .v-card__text,
.slumulation-sidebar-card .v-card__text {
    padding-top: 10px;
}

.slumulation-map-frame {
    width: min(100%, 720px);
    margin-inline: auto;
}

.slumulation-map {
    display: grid;
    aspect-ratio: 1;
    width: 100%;
    border: 2px solid #263445;
    background: #f8fafc;
}

.slumulation-cell {
    position: relative;
    min-width: 0;
    min-height: 0;
    border: 0;
    overflow: hidden;
}

.slumulation-household-markers {
    position: absolute;
    inset: 18% 10%;
    z-index: 2;
    display: grid;
    border: 1px solid rgba(255, 255, 255, 0.9);
    box-shadow: 0 0 0 1px rgba(23, 32, 51, 0.36);
    pointer-events: none;
}

.slumulation-household-segment {
    min-width: 0;
    min-height: 0;
}

.slumulation-household-neutral {
    box-shadow: inset 0 0 0 1px rgba(23, 32, 51, 0.72);
}

.slumulation-developer-marker {
    position: absolute;
    inset: 20%;
    z-index: 2;
    display: block;
    border: 1px solid #ffffff;
    background: #111827;
    box-shadow: 0 0 0 1px rgba(23, 32, 51, 0.38);
    transform: rotate(45deg);
    pointer-events: none;
}

.slumulation-status-grid,
.slumulation-metrics-grid,
.slumulation-parameter-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 9px;
}

.slumulation-status-item,
.slumulation-metric-item,
.slumulation-parameter-item {
    min-height: 58px;
    padding: 8px 10px;
    border: 1px solid #dde4ec;
    border-radius: 8px;
    background: #f8fafc;
}

.slumulation-status-label,
.slumulation-metric-label,
.slumulation-parameter-label {
    margin-bottom: 4px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0;
    text-transform: uppercase;
    color: #596a7d;
}

.slumulation-status-value,
.slumulation-metric-value,
.slumulation-parameter-value {
    overflow-wrap: anywhere;
    font-size: 0.94rem;
    font-weight: 650;
    line-height: 1.28;
    letter-spacing: 0;
    color: #172033;
}

.slumulation-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 14px;
    padding: 8px 0 0;
}

.slumulation-legend-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.84rem;
    color: #334155;
}

.slumulation-swatch {
    width: 14px;
    height: 14px;
    flex: 0 0 auto;
    border: 1px solid rgba(23, 32, 51, 0.22);
}

.slumulation-swatch-marker {
    box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.72);
}

.slumulation-swatch-developer {
    width: 11px;
    height: 11px;
    margin-inline: 2px;
    transform: rotate(45deg);
}

.slumulation-full-dashboard {
    width: 100%;
}

.slumulation-controls .v-select__selections {
    min-width: 0;
}

.slumulation-controls .v-select__selection--comma {
    overflow: visible;
    overflow-wrap: anywhere;
    text-overflow: clip;
    white-space: normal;
}

.slumulation-controls .v-input__slot {
    height: auto;
    min-height: 40px;
}

.slumulation-control-buttons {
    width: 100%;
    flex-wrap: wrap !important;
    align-items: stretch;
}

.slumulation-control-buttons .v-btn {
    box-sizing: border-box;
    flex: 1 1 72px;
    min-width: 72px !important;
    max-width: 100%;
    width: auto !important;
    padding-inline: 6px !important;
    letter-spacing: 0;
}

.slumulation-control-buttons .v-btn__content {
    min-width: 0;
    overflow-wrap: anywhere;
    white-space: normal;
}

@media (max-width: 700px) {
    .slumulation-shell {
        padding-inline: 2px;
    }

    .slumulation-map-frame {
        width: 100%;
    }

    .slumulation-legend {
        gap: 6px 10px;
    }

    .slumulation-legend-item {
        font-size: 0.78rem;
    }
}
"""


@dataclass(slots=True)
class SlumulationAppState:
    world: WorldState
    parameters: SetupParameters
    rng: Random
    experiment_name: str
    parameter_index: int
    seed: int | str
    emitted_step: int = 0
    stopped: bool = False
    stop_reason: str = ""


def experiment_options() -> list[dict[str, str]]:
    return [
        {"name": experiment.name, "label": experiment.name}
        for experiment in SELECTED_EXPERIMENTS
    ]


def experiment_spec_for_name(name: str):
    try:
        return SELECTED_EXPERIMENT_REGISTRY[name]
    except KeyError as exc:
        available = ", ".join(SELECTED_EXPERIMENT_REGISTRY)
        raise ValueError(
            f"Unknown or excluded Slumulation experiment {name!r}; "
            f"available: {available}."
        ) from exc


def parameter_condition_options(experiment_name: str) -> list[dict[str, object]]:
    experiment = experiment_spec_for_name(experiment_name)
    return [
        {
            "index": index,
            "name": parameter_combination.label,
            "label": parameter_combination.label,
            "values": dict(parameter_combination.values),
        }
        for index, parameter_combination in enumerate(experiment.parameter_combinations)
    ]


def parameter_combination_for_index(experiment_name: str, parameter_index: int):
    experiment = experiment_spec_for_name(experiment_name)
    if parameter_index < 0 or parameter_index >= len(experiment.parameter_combinations):
        raise IndexError(
            f"Parameter condition index {parameter_index} is outside "
            f"{experiment.name!r} conditions."
        )
    return experiment.parameter_combinations[parameter_index]


def create_app_state(
    experiment_name: str = DEFAULT_EXPERIMENT_NAME,
    parameter_index: int = 0,
    seed: int | str = DEFAULT_SEED,
) -> SlumulationAppState:
    parameter_combination = parameter_combination_for_index(
        experiment_name,
        parameter_index,
    )
    parameters = load_setup_parameters(parameter_combination)
    setup_result = setup_initial_world(parameter_values=parameters, seed=seed)
    return SlumulationAppState(
        world=setup_result.world,
        parameters=setup_result.parameters,
        rng=Random(seed),
        experiment_name=experiment_name,
        parameter_index=parameter_index,
        seed=seed,
    )


def step_app_state(state: SlumulationAppState, step_fn=slumulate_step):
    if state.stopped:
        return state

    result = step_fn(state.world, state.parameters, state.rng)
    stopped = bool(getattr(result, "stopped"))
    tick_advanced = bool(getattr(result, "tick_advanced"))

    if tick_advanced:
        state.emitted_step += 1

    if stopped or not tick_advanced:
        state.stopped = True
        if stopped and not tick_advanced:
            state.stop_reason = (
                "Stopped: tick did not advance at source runtime boundary."
            )
        elif stopped:
            state.stop_reason = "Stopped at source runtime boundary."
        else:
            state.stop_reason = "Step returned without advancing a tick."

    return state


def run_app_steps(
    state: SlumulationAppState,
    steps: int,
    step_fn=slumulate_step,
) -> SlumulationAppState:
    if steps < 0:
        raise ValueError(f"steps must be non-negative, got {steps}.")

    for _ in range(steps):
        if state.stopped:
            break
        step_app_state(state, step_fn=step_fn)
    return state


def patch_grid(world: WorldState) -> list[list[dict[str, Any]]]:
    household_counts: dict[Coordinate, Counter[str]] = {}
    for household in world.households:
        counts = household_counts.setdefault(household.coordinate, Counter())
        counts[_normalized_income_class(household.income_class)] += 1

    developer_counts: dict[Coordinate, int] = {}
    for developer in world.developers:
        developer_counts[developer.coordinate] = (
            developer_counts.get(developer.coordinate, 0) + 1
        )

    x_min, x_max, y_min, y_max = world.bounds
    rows: list[list[dict[str, Any]]] = []
    for y in range(y_max, y_min - 1, -1):
        row: list[dict[str, Any]] = []
        for x in range(x_min, x_max + 1):
            patch = world.patch_at(x, y)
            row.append(_cell_from_patch(patch, household_counts, developer_counts))
        rows.append(row)
    return rows


def patch_grid_style(world: WorldState) -> str:
    return (
        f"grid-template-columns: repeat({world.width}, minmax(0, 1fr)); "
        f"grid-template-rows: repeat({world.height}, minmax(0, 1fr));"
    )


def cell_style(cell: Mapping[str, Any], layer_name: str) -> str:
    if layer_name == "composite":
        color = (
            _COMPOSITE_SLUM_COLOR
            if cell.get("slum_status", cell["slum"])
            else _composite_rent_color(float(cell["rent"]))
        )
    elif layer_name == "slum_status":
        color = "#7f1d1d" if cell.get("slum_status", cell["slum"]) else "#f8fafc"
    elif layer_name == "rent":
        color = _rent_color(float(cell["rent"]))
    elif layer_name == "ward":
        color = _WARD_COLORS.get(int(cell["ward"]), "#f8fafc")
    elif layer_name == "occupancy":
        color = _occupancy_color(int(cell["num_occupants"]), bool(cell["available"]))
    elif layer_name == "resicat":
        color = _RESICAT_COLORS.get(int(cell["resicat"]), "#111827")
    elif layer_name == "developers":
        color = "#f8fafc"
    else:
        available = ", ".join(_LAYER_LABELS)
        raise ValueError(f"Unknown Slumulation map layer {layer_name!r}: {available}.")

    return f"background: {color};"


def layer_options() -> list[dict[str, str]]:
    return [dict(option) for option in LAYER_OPTIONS]


def metric_items(
    world: WorldState,
    emitted_step: int,
    stopped: bool,
    stop_reason: str,
) -> list[tuple[str, str]]:
    summary = world.summary
    items: list[tuple[str, Any]] = [
        ("Current Time", world.time),
        ("Emitted Step", emitted_step),
        ("Run State", "Stopped" if stopped else "Ready"),
        ("Stop Status", stop_reason or "none"),
        ("Population", summary.population),
        ("Slum Population", summary.slum_pop),
        ("Slum Population Percent", summary.slum_pop_percent),
        ("Number Of Slums", summary.num_slums),
        ("Average Income", summary.avg_income),
        ("Highest Rent", summary.highest_rent),
        ("Lowest Rent", summary.lowest_rent),
        ("Number Searching", summary.num_searching),
        ("Developers", summary.num_developers),
        ("Slum Area Percent", summary.slum_area_percent),
        ("Average Density", summary.avg_density),
    ]
    for metric_name in SOURCE_EMITTED_METRIC_NAMES:
        crosswalk = METRIC_CROSSWALK_BY_NETLOGO_NAME[metric_name]
        items.append(
            (_display_metric_label(metric_name), getattr(summary, crosswalk.mesa_alias))
        )
    return [(label, format_metric_value(value)) for label, value in items]


def format_metric_value(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _cell_from_patch(
    patch: PatchState,
    household_counts: Mapping[Coordinate, Counter[str]],
    developer_counts: Mapping[Coordinate, int],
) -> dict[str, Any]:
    coordinate_counts = household_counts.get(patch.coordinate, Counter())
    income_class_counts = {
        income_class: coordinate_counts.get(income_class, 0)
        for income_class in _INCOME_CLASS_ORDER
    }
    neutral_count = income_class_counts["neutral"]
    return {
        "x": patch.x,
        "y": patch.y,
        "ward": patch.ward,
        "rent": patch.rent,
        "rent_payable": patch.rent_payable,
        "occupied": patch.occupied,
        "occupancy": patch.num_occupants,
        "num_occupants": patch.num_occupants,
        "num_units": patch.num_units,
        "available": patch.available,
        "slum": patch.slum,
        "slum_status": patch.slum,
        "slum_occupants": patch.slum_occupants,
        "resicat": patch.resicat,
        "household_count": sum(income_class_counts.values()),
        "income_class_counts": income_class_counts,
        "red_count": income_class_counts["red"],
        "blue_count": income_class_counts["blue"],
        "green_count": income_class_counts["green"],
        "neutral_count": neutral_count,
        "unclassified_count": neutral_count,
        "developer_count": developer_counts.get(patch.coordinate, 0),
    }


def _normalized_income_class(income_class: str | None) -> str:
    if income_class in _INCOME_CLASS_ORDER[:-1]:
        return income_class
    return "neutral"


def _composite_rent_color(rent: float) -> str:
    if rent <= 0:
        return "#fffde7"
    bucket = min(8, max(0, int(rent // 160)))
    palette = (
        "#fff9c4",
        "#fff59d",
        "#fff176",
        "#ffee58",
        "#fdd835",
        "#fbc02d",
        "#f9a825",
        "#f57f17",
        "#e65100",
    )
    return palette[bucket]


def _rent_color(rent: float) -> str:
    if rent <= 0:
        return "#f8fafc"
    bucket = min(8, max(0, int(rent // 160)))
    palette = (
        "#e0f2fe",
        "#bae6fd",
        "#7dd3fc",
        "#38bdf8",
        "#0ea5e9",
        "#0284c7",
        "#0369a1",
        "#075985",
        "#0c4a6e",
    )
    return palette[bucket]


def _display_metric_label(metric_name: str) -> str:
    return metric_name.replace("-", " ").replace("_", " ").title()


def _occupancy_color(num_occupants: int, available: bool) -> str:
    if num_occupants <= 0:
        return "#f8fafc" if available else "#e5e7eb"
    if num_occupants == 1:
        return "#bbf7d0"
    if num_occupants == 2:
        return "#fde68a"
    if num_occupants == 3:
        return "#fdba74"
    return "#dc2626"


def _render_item_grid(
    items: list[tuple[str, str]],
    *,
    classes: list[str],
) -> None:
    item_class, label_class, value_class, grid_class = classes
    blocks = []
    for label, value in items:
        blocks.append(
            f'<div class="{escape(item_class)}">'
            f'<div class="{escape(label_class)}">{escape(label)}</div>'
            f'<div class="{escape(value_class)}">{escape(value)}</div>'
            "</div>"
        )
    solara.HTML(tag="div", unsafe_innerHTML="".join(blocks), classes=[grid_class])


def _render_patch_map(world: WorldState, layer_name: str) -> None:
    solara.HTML(
        tag="div",
        unsafe_innerHTML=_patch_map_html(
            world,
            layer_name,
            test_id=(
                "slumulation-composite-map"
                if layer_name == "composite"
                else f"slumulation-{layer_name}-map"
            ),
        ),
    )


def _patch_map_html(
    world: WorldState,
    layer_name: str,
    *,
    include_legend: bool = True,
    test_id: str,
    frame_classes: tuple[str, ...] = (),
) -> str:
    cells = []
    for row in patch_grid(world):
        for cell in row:
            marker_html = ""
            if layer_name == "composite":
                marker_html = _household_marker_html(cell)
            elif layer_name == "developers":
                marker_html = _developer_marker_html(cell)
            cells.append(
                '<div class="slumulation-cell" '
                f'data-x="{cell["x"]}" data-y="{cell["y"]}" '
                f'title="{escape(_cell_tooltip(cell))}" '
                f'style="{escape(cell_style(cell, layer_name))}">'
                f"{marker_html}</div>"
            )

    frame_class = " ".join(("slumulation-map-frame", *frame_classes))
    composite_class = " slumulation-composite-map" if layer_name == "composite" else ""
    legend = _legend_html(layer_name) if include_legend else ""
    return (
        f'<div class="{escape(frame_class)}">'
        f'<div class="slumulation-map{composite_class}" '
        f'data-testid="{escape(test_id)}" data-layer="{escape(layer_name)}" '
        f'style="{escape(patch_grid_style(world))}">'
        f"{''.join(cells)}"
        "</div>"
        f"{legend}"
        "</div>"
    )


def _cell_tooltip(cell: Mapping[str, Any]) -> str:
    slum = "yes" if cell.get("slum_status", cell["slum"]) else "no"
    return (
        f"Coordinates: ({cell['x']}, {cell['y']}); "
        f"ward: {cell['ward']}; rent: {format_metric_value(cell['rent'])}; "
        f"slum: {slum}; "
        f"lower/red: {cell['red_count']}; middle/blue: {cell['blue_count']}; "
        f"higher/green: {cell['green_count']}; "
        f"neutral/unclassified: {cell['neutral_count']}; "
        f"occupancy: {cell['num_occupants']}; "
        f"developers: {cell['developer_count']}; resicat: {cell['resicat']}"
    )


def _household_marker_html(cell: Mapping[str, Any]) -> str:
    segments = [
        (income_class, int(cell[f"{income_class}_count"]))
        for income_class in _INCOME_CLASS_ORDER
        if int(cell[f"{income_class}_count"]) > 0
    ]
    if not segments:
        return ""

    segment_html = []
    for income_class, count in segments:
        segment_html.append(
            '<span class="slumulation-household-segment '
            f'slumulation-household-{escape(income_class)}" '
            f'data-income-class="{escape(income_class)}" data-count="{count}" '
            f'style="background: {escape(_INCOME_CLASS_COLORS[income_class])};">'
            "</span>"
        )
    return (
        '<span class="slumulation-household-markers" '
        f'data-segment-count="{len(segments)}" '
        f'style="grid-template-columns: repeat({len(segments)}, minmax(0, 1fr));">'
        f"{''.join(segment_html)}</span>"
    )


def _developer_marker_html(cell: Mapping[str, Any]) -> str:
    count = int(cell["developer_count"])
    if count <= 0:
        return ""
    return (
        '<span class="slumulation-developer-marker" '
        f'data-count="{count}" style="background: {_DEVELOPER_COLOR};"></span>'
    )


def _legend_html(layer_name: str) -> str:
    if layer_name == "composite":
        entries = (
            ("#fff9c4", "Lower rent", ""),
            ("#e65100", "Higher rent", ""),
            (_COMPOSITE_SLUM_COLOR, "Slum", ""),
            (_INCOME_CLASS_COLORS["red"], _INCOME_CLASS_LABELS["red"], "marker"),
            (_INCOME_CLASS_COLORS["blue"], _INCOME_CLASS_LABELS["blue"], "marker"),
            (
                _INCOME_CLASS_COLORS["green"],
                _INCOME_CLASS_LABELS["green"],
                "marker",
            ),
            (
                _INCOME_CLASS_COLORS["neutral"],
                _INCOME_CLASS_LABELS["neutral"],
                "marker",
            ),
        )
    elif layer_name == "slum_status":
        entries = (
            ("#7f1d1d", "Slum", ""),
            ("#f8fafc", "Not slum", ""),
        )
    elif layer_name == "rent":
        entries = (
            ("#e0f2fe", "Low rent", ""),
            ("#0ea5e9", "Mid rent", ""),
            ("#0c4a6e", "High rent", ""),
        )
    elif layer_name == "ward":
        entries = tuple(
            (color, f"Ward {ward}", "") for ward, color in sorted(_WARD_COLORS.items())
        )
    elif layer_name == "occupancy":
        entries = (
            ("#f8fafc", "Empty", ""),
            ("#bbf7d0", "1 occupant", ""),
            ("#fde68a", "2 occupants", ""),
            ("#dc2626", "4+ occupants", ""),
        )
    elif layer_name == "resicat":
        entries = tuple(
            (_RESICAT_COLORS[index], f"Category {index}", "")
            for index in sorted(_RESICAT_COLORS)
        )
    elif layer_name == "developers":
        entries = ((_DEVELOPER_COLOR, "Developer", "developer"),)
    else:
        entries = ()

    swatches = []
    for color, label, kind in entries:
        swatch_class = "slumulation-swatch"
        if kind:
            swatch_class += f" slumulation-swatch-{kind}"
        swatches.append(
            '<span class="slumulation-legend-item">'
            f'<span class="{escape(swatch_class)}" '
            f'style="background: {escape(color)};"></span>'
            f"{escape(label)}</span>"
        )
    return f'<div class="slumulation-legend">{"".join(swatches)}</div>'


def _parameter_items(parameters: SetupParameters) -> list[tuple[str, str]]:
    return [
        (name, format_metric_value(value))
        for name, value in parameters.values
        if name in PARAMETER_FIELD_ORDER
    ]


@solara.component
def map_panel(
    state: SlumulationAppState,
    layer_name: str,
    render_revision: int = 0,
) -> None:
    update_counter.get()
    with solara.Card("Patch Map", margin=0, classes=["slumulation-card"]):
        _render_patch_map(state.world, layer_name)


@solara.component
def run_state_panel(
    state: SlumulationAppState,
    render_revision: int = 0,
) -> None:
    update_counter.get()
    items = [
        ("Experiment", state.experiment_name),
        (
            "Condition",
            parameter_combination_for_index(
                state.experiment_name,
                state.parameter_index,
            ).label,
        ),
        ("Seed", str(state.seed)),
        ("Step", str(state.emitted_step)),
        ("Time", str(state.world.time)),
        ("Run state", "stopped" if state.stopped else "ready"),
        ("Stop status", state.stop_reason or "none"),
    ]
    with solara.Card("Run State", margin=0, classes=["slumulation-card"]):
        _render_item_grid(
            items,
            classes=[
                "slumulation-status-item",
                "slumulation-status-label",
                "slumulation-status-value",
                "slumulation-status-grid",
            ],
        )


@solara.component
def metrics_panel(
    state: SlumulationAppState,
    render_revision: int = 0,
) -> None:
    update_counter.get()
    with solara.Card("Metrics", margin=0, classes=["slumulation-card"]):
        _render_item_grid(
            metric_items(
                state.world,
                state.emitted_step,
                state.stopped,
                state.stop_reason,
            ),
            classes=[
                "slumulation-metric-item",
                "slumulation-metric-label",
                "slumulation-metric-value",
                "slumulation-metrics-grid",
            ],
        )


@solara.component
def parameter_panel(state: SlumulationAppState) -> None:
    update_counter.get()
    with solara.Card("Parameters", margin=0, classes=["slumulation-card"]):
        _render_item_grid(
            _parameter_items(state.parameters),
            classes=[
                "slumulation-parameter-item",
                "slumulation-parameter-label",
                "slumulation-parameter-value",
                "slumulation-parameter-grid",
            ],
        )


@solara.component
def dashboard_panel(
    state: SlumulationAppState,
    layer_name: str,
    render_revision: int = 0,
) -> None:
    with solara.Div(
        classes=["slumulation-full-dashboard"],
        attributes={"data-testid": "slumulation-full-dashboard"},
    ):
        solara.HTML(
            tag="span",
            style="display: none;",
            attributes={
                "data-testid": "slumulation-full-gui-state",
                "data-experiment": state.experiment_name,
                "data-parameter-index": str(state.parameter_index),
                "data-parameter-label": parameter_combination_for_index(
                    state.experiment_name,
                    state.parameter_index,
                ).label,
                "data-seed": str(state.seed),
                "data-step": str(state.emitted_step),
                "data-world-time": str(state.world.time),
                "data-layer": layer_name,
            },
        )
        with solara.Column(gap="12px", classes=["slumulation-shell"]):
            with solara.Row(
                gap="12px",
                style={
                    "align-items": "stretch",
                    "flex-wrap": "wrap",
                    "width": "100%",
                },
            ):
                with solara.Column(
                    gap="12px",
                    style={"flex": "1.1 1 520px", "min-width": "320px"},
                ):
                    map_panel(state, layer_name, render_revision)
                with solara.Column(
                    gap="12px",
                    style={"flex": "0.9 1 360px", "min-width": "300px"},
                ):
                    run_state_panel(state, render_revision)
                    parameter_panel(state)
            metrics_panel(state, render_revision)


@solara.component
def page() -> None:
    solara.Style(SLUMULATION_CSS)
    update_counter.get()

    experiment_names = [option["name"] for option in experiment_options()]
    layer_labels = {option["name"]: option["label"] for option in layer_options()}
    layer_names_by_label = {label: name for name, label in layer_labels.items()}

    experiment_name = solara.use_reactive(DEFAULT_EXPERIMENT_NAME)
    parameter_index = solara.use_reactive(0)
    seed = solara.use_reactive(DEFAULT_SEED)
    layer_name = solara.use_reactive(DEFAULT_LAYER_NAME)
    run_steps = solara.use_reactive(DEFAULT_RUN_STEPS)
    playing = solara.use_reactive(False)
    playback_generation = solara.use_reactive(0)
    step_in_flight = solara.use_reactive(False)
    render_revision = solara.use_reactive(0)

    initial_state = solara.use_memo(create_app_state, dependencies=[])
    reactive_state = solara.use_reactive(initial_state)
    playback_wakeup = solara.use_memo(asyncio.Event, dependencies=[])

    def repaint_state_panels() -> None:
        render_revision.set(render_revision.value + 1)

    def stop_playback() -> None:
        playing.value = False
        playback_generation.value += 1
        playback_wakeup.set()

    def reset_state(
        *,
        experiment_value: str | None = None,
        parameter_value: int | None = None,
        seed_value: int | str | None = None,
    ) -> None:
        stop_playback()
        resolved_experiment = experiment_value or experiment_name.value
        resolved_parameter = (
            parameter_index.value if parameter_value is None else parameter_value
        )
        resolved_seed = seed.value if seed_value is None else seed_value
        reactive_state.value = create_app_state(
            resolved_experiment,
            resolved_parameter,
            resolved_seed,
        )
        repaint_state_panels()
        force_update()

    def set_experiment(value: str) -> None:
        experiment_name.value = value
        parameter_index.value = 0
        reset_state(experiment_value=value, parameter_value=0)

    def set_parameter_condition(label: str) -> None:
        options = parameter_condition_options(experiment_name.value)
        index_by_label = {
            str(option["label"]): int(option["index"]) for option in options
        }
        new_index = index_by_label[label]
        parameter_index.value = new_index
        reset_state(parameter_value=new_index)

    def set_seed(value: int | None) -> None:
        new_seed = DEFAULT_SEED if value is None else int(value)
        seed.value = new_seed
        reset_state(seed_value=new_seed)

    def reset_button() -> None:
        reset_state()

    def step_button() -> None:
        if playing.value or step_in_flight.value or reactive_state.value.stopped:
            return
        step_app_state(reactive_state.value)
        repaint_state_panels()
        force_update()

    def run_button() -> None:
        if reactive_state.value.stopped:
            stop_playback()
        elif playing.value:
            stop_playback()
        else:
            playback_generation.value += 1
            playing.value = True
            playback_wakeup.set()
        force_update()

    def playback_is_current(
        generation: int,
        active_state: SlumulationAppState,
    ) -> bool:
        return (
            playing.value
            and playback_generation.value == generation
            and reactive_state.value is active_state
        )

    async def playback_controller() -> None:
        while True:
            await playback_wakeup.wait()
            playback_wakeup.clear()

            if not playing.value or reactive_state.value.stopped:
                continue

            generation = playback_generation.value
            active_state = reactive_state.value

            while playback_is_current(generation, active_state):
                if active_state.stopped:
                    break

                await asyncio.sleep(DEFAULT_PLAY_INTERVAL_MS / 1000)
                if (
                    not playback_is_current(generation, active_state)
                    or active_state.stopped
                ):
                    break

                steps_this_interval = run_steps.value
                for _ in range(steps_this_interval):
                    if (
                        not playback_is_current(generation, active_state)
                        or active_state.stopped
                    ):
                        break

                    step_in_flight.value = True
                    try:
                        await asyncio.to_thread(run_app_steps, active_state, 1)
                    finally:
                        step_in_flight.value = False

                    if not playback_is_current(generation, active_state):
                        break
                    if active_state.stopped:
                        stop_playback()
                        repaint_state_panels()
                        force_update()
                        break

                if (
                    not playback_is_current(generation, active_state)
                    or active_state.stopped
                ):
                    break

                repaint_state_panels()
                force_update()

    solara.lab.use_task(
        playback_controller,
        dependencies=[],
        prefer_threaded=False,
    )

    condition_options = parameter_condition_options(experiment_name.value)
    condition_labels = [str(option["label"]) for option in condition_options]
    selected_condition = condition_options[parameter_index.value]["label"]
    selected_layer_label = layer_labels[layer_name.value]

    with solara.AppBar():
        solara.AppBarTitle("Slumulation")

    with solara.Sidebar(), solara.Column(gap="10px"):
        with solara.Card(
            "Controls",
            classes=["slumulation-sidebar-card", "slumulation-controls"],
        ):
            solara.Select(
                "Experiment",
                values=experiment_names,
                value=experiment_name.value,
                on_value=set_experiment,
                dense=True,
            )
            solara.Select(
                "Parameter condition",
                values=condition_labels,
                value=str(selected_condition),
                on_value=set_parameter_condition,
                dense=True,
            )
            solara.InputInt(
                "Seed",
                value=seed.value,
                on_value=set_seed,
                dense=True,
                continuous_update=False,
            )
            solara.Select(
                "Patch layer",
                values=list(layer_names_by_label),
                value=selected_layer_label,
                on_value=lambda label: layer_name.set(layer_names_by_label[label]),
                dense=True,
            )
            solara.SliderInt(
                "Run steps",
                value=run_steps,
                on_value=lambda value: run_steps.set(value),
                min=1,
                max=10,
                step=1,
            )
            with solara.Row(
                gap="8px",
                classes=["slumulation-control-buttons"],
            ):
                solara.Button(label="Reset", color="primary", on_click=reset_button)
                solara.Button(
                    label="Pause" if playing.value else "Run",
                    color="primary",
                    on_click=run_button,
                    disabled=reactive_state.value.stopped,
                )
                solara.Button(
                    label="Step",
                    color="primary",
                    on_click=step_button,
                    disabled=(
                        playing.value
                        or step_in_flight.value
                        or reactive_state.value.stopped
                    ),
                )

    dashboard_panel(
        reactive_state.value,
        layer_name.value,
        render_revision.value,
    )


__all__ = [
    "DEFAULT_EXPERIMENT_NAME",
    "DEFAULT_LAYER_NAME",
    "DEFAULT_PLAY_INTERVAL_MS",
    "DEFAULT_RUN_STEPS",
    "DEFAULT_SEED",
    "LAYER_OPTIONS",
    "SlumulationAppState",
    "cell_style",
    "create_app_state",
    "experiment_options",
    "experiment_spec_for_name",
    "format_metric_value",
    "layer_options",
    "metric_items",
    "page",
    "parameter_combination_for_index",
    "parameter_condition_options",
    "patch_grid",
    "patch_grid_style",
    "run_app_steps",
    "step_app_state",
]
