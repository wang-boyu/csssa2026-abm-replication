from __future__ import annotations

import asyncio
from functools import lru_cache
from html import escape
from typing import Any

import solara
from mesa.visualization.solara_viz import force_update, update_counter

from sakoda.model import (
    JUMP_RULE_ENDPOINT_ONLY,
    JUMP_RULE_NO_ADJACENT_AVAILABLE,
    JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
    MOVEMENT_ORDER_ALL_RANDOM,
    MOVEMENT_ORDER_GROUPS_SEQUENTIAL,
    SakodaModel,
)
from sakoda.replay import (
    ALL_SCENARIO_TERMINAL_SPECS,
    CROSSROADS_TRAJECTORY_CYCLES,
    PUBLICATION_JUMP_RULE,
    PUBLICATION_MOVEMENT_ORDER,
    PUBLICATION_SEED,
    STABLE_MODEL_STOP_REASON,
    PublicationBoardSnapshot,
    replay_all_scenario_terminals,
    replay_crossroads_trajectory,
    terminal_spec_for_scenario,
)
from sakoda.scenarios import DEFAULT_SEEDS, SCENARIO_LIST, SQUARES

DEFAULT_SCENARIO_NAME = "crossroads"
DEFAULT_SEED = DEFAULT_SEEDS[0]
DEFAULT_PLAY_INTERVAL_MS = 250
VIEW_OPTIONS: tuple[str, str, str] = (
    "Inspection",
    "Crossroads trajectory",
    "All scenarios",
)
FULL_GUI_CAPTURE_ANCHOR_TEST_ID = "sakoda-full-gui-capture-anchor"
FULL_GUI_CAPTURE_SELECTOR = 'body:has([data-testid="sakoda-full-gui-capture-anchor"])'
CONTROLS_CAPTURE_SELECTOR = ".sakoda-controls"
CROSSROADS_TRIPTYCH_TEST_ID = "sakoda-crossroads-triptych"
ALL_SCENARIOS_GALLERY_TEST_ID = "sakoda-all-scenarios-gallery"

SCENARIO_LABELS = {scenario.name: scenario.display_name for scenario in SCENARIO_LIST}
SCENARIO_NAMES_BY_LABEL = {label: name for name, label in SCENARIO_LABELS.items()}

MAIN_CONVENTION_LABEL = "Main evidence: no_adjacent_improvement + all_random"
CONVENTION_PRESETS: tuple[dict[str, str], ...] = (
    {
        "label": MAIN_CONVENTION_LABEL,
        "jump_rule": JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
        "movement_order": MOVEMENT_ORDER_ALL_RANDOM,
        "role": "main evidence",
    },
    {
        "label": "Diagnostic/supporting: no_adjacent_available + all_random",
        "jump_rule": JUMP_RULE_NO_ADJACENT_AVAILABLE,
        "movement_order": MOVEMENT_ORDER_ALL_RANDOM,
        "role": "diagnostic/supporting",
    },
    {
        "label": "Diagnostic/supporting: endpoint_only + all_random",
        "jump_rule": JUMP_RULE_ENDPOINT_ONLY,
        "movement_order": MOVEMENT_ORDER_ALL_RANDOM,
        "role": "diagnostic/supporting",
    },
    {
        "label": ("Diagnostic/supporting: no_adjacent_improvement + groups_sequential"),
        "jump_rule": JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
        "movement_order": MOVEMENT_ORDER_GROUPS_SEQUENTIAL,
        "role": "diagnostic/supporting",
    },
)
CONVENTIONS_BY_LABEL = {preset["label"]: preset for preset in CONVENTION_PRESETS}

SAKODA_CSS = """
.sakoda-shell {
    width: 100%;
    padding: 8px 8px 18px;
    color: #172033;
}

div:has(> b > a[href="https://solara.dev"]) {
    position: static !important;
    text-align: right;
}

.sakoda-sidebar-card {
    border: 1px solid #d7dde5;
    box-shadow: none !important;
    background: #f8fafc;
}

.sakoda-sidebar-card .v-card__title,
.sakoda-card .v-card__title {
    padding-bottom: 0;
    font-size: 0.98rem;
    line-height: 1.25;
    color: #25364d;
}

.sakoda-sidebar-card .v-card__text,
.sakoda-card .v-card__text {
    padding-top: 10px;
}

.sakoda-convention-select {
    margin-top: 8px;
}

.sakoda-convention-select .v-select__selection--comma {
    overflow: visible;
    overflow-wrap: anywhere;
    text-overflow: clip;
    white-space: normal;
}

.sakoda-board-frame {
    width: min(100%, 640px);
}

.sakoda-board {
    display: grid;
    aspect-ratio: 1;
    width: 100%;
    border: 2px solid #263445;
    background: #f6f4ef;
}

.sakoda-cell {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    min-width: 0;
    min-height: 0;
    border: 1px solid #9aa6b2;
    background: #f5f1e8;
}

.sakoda-cell-even {
    background: #e2e8f0;
}

.sakoda-piece {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    width: 76%;
    height: 76%;
    border-radius: 5px;
    border: 1px solid rgba(23, 32, 51, 0.18);
    background: rgba(255, 255, 255, 0.88);
}

.sakoda-square-piece {
    color: #0f766e;
}

.sakoda-cross-piece {
    color: #b45309;
}

.sakoda-piece-mark {
    position: relative;
    display: block;
    width: 17px;
    height: 17px;
    flex: 0 0 auto;
}

.sakoda-square-mark {
    border: 3px solid #0f766e;
    background: #d9f4ee;
}

.sakoda-cross-mark::before,
.sakoda-cross-mark::after {
    position: absolute;
    left: 7px;
    top: -1px;
    width: 3px;
    height: 20px;
    border-radius: 2px;
    background: #b45309;
    content: "";
}

.sakoda-cross-mark::before {
    transform: rotate(45deg);
}

.sakoda-cross-mark::after {
    transform: rotate(-45deg);
}

.sakoda-piece-label {
    font-size: 0.86rem;
    font-weight: 800;
    line-height: 1;
    letter-spacing: 0;
}

.sakoda-status-grid,
.sakoda-metrics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 9px;
}

.sakoda-status-item,
.sakoda-metric-item {
    min-height: 58px;
    padding: 8px 10px;
    border: 1px solid #dde4ec;
    border-radius: 8px;
    background: #f8fafc;
}

.sakoda-status-label,
.sakoda-metric-label {
    margin-bottom: 4px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0;
    text-transform: uppercase;
    color: #596a7d;
}

.sakoda-status-value,
.sakoda-metric-value {
    overflow-wrap: anywhere;
    font-size: 0.96rem;
    font-weight: 650;
    line-height: 1.28;
    letter-spacing: 0;
    color: #172033;
}

.sakoda-convention-main {
    border-color: #0f766e;
    background: #effaf7;
}

.sakoda-convention-diagnostic {
    border-color: #f59e0b;
    background: #fff8eb;
}

.sakoda-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 14px;
    padding: 7px 0 0;
}

.sakoda-legend-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.84rem;
    color: #334155;
}

.sakoda-mini-square,
.sakoda-mini-cross {
    position: relative;
    width: 14px;
    height: 14px;
    flex: 0 0 auto;
}

.sakoda-mini-square {
    border: 2px solid #0f766e;
    background: #d9f4ee;
}

.sakoda-mini-cross::before,
.sakoda-mini-cross::after {
    position: absolute;
    left: 6px;
    top: -2px;
    width: 2px;
    height: 18px;
    border-radius: 1px;
    background: #b45309;
    content: "";
}

.sakoda-mini-cross::before {
    transform: rotate(45deg);
}

.sakoda-mini-cross::after {
    transform: rotate(-45deg);
}

.sakoda-mode-toggle,
.sakoda-full-dashboard {
    width: 100%;
}

.sakoda-mode-toggle {
    display: grid !important;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    max-width: 100%;
}

.sakoda-mode-toggle .v-btn {
    box-sizing: border-box;
    min-width: 0 !important;
    max-width: 100%;
    width: 100%;
    min-height: 38px;
    height: auto !important;
    padding: 6px !important;
    letter-spacing: 0;
}

.sakoda-mode-toggle .v-btn__content {
    min-width: 0;
    width: 100%;
    overflow-wrap: anywhere;
    line-height: 1.15;
    text-align: center;
    white-space: normal;
}

.sakoda-control-actions {
    flex-wrap: wrap;
    width: 100%;
}

.sakoda-control-actions .v-btn {
    min-width: 0 !important;
    flex: 1 1 72px;
}

.sakoda-publication-view {
    width: 100%;
    padding: 10px 8px 20px;
    color: #172033;
}

.sakoda-publication-heading {
    display: flex;
    align-items: end;
    justify-content: space-between;
    gap: 10px 20px;
    margin: 0 0 10px;
    border-bottom: 1px solid #cbd5e1;
    padding: 0 0 8px;
}

.sakoda-publication-heading h1 {
    margin: 0;
    font-size: 1.2rem;
    font-weight: 750;
    line-height: 1.2;
    letter-spacing: 0;
    color: #172033;
}

.sakoda-publication-context {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 4px 12px;
    font-size: 0.76rem;
    line-height: 1.3;
    color: #526174;
}

.sakoda-crossroads-triptych-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    align-items: start;
    gap: 14px;
    width: 100%;
}

.sakoda-crossroads-triptych-panel {
    min-width: 0;
}

.sakoda-crossroads-triptych-label {
    margin: 0 0 6px;
    font-size: 0.88rem;
    font-weight: 750;
    line-height: 1.2;
    text-align: center;
    letter-spacing: 0;
    color: #334155;
}

.sakoda-publication-board-frame {
    width: 100%;
    margin-inline: auto;
}

.sakoda-publication-board {
    border-width: 1px;
}

.sakoda-publication-view .sakoda-cell {
    border-width: 0.75px;
}

.sakoda-publication-view .sakoda-piece {
    gap: 1px;
    width: 86%;
    height: 86%;
    border-radius: 3px;
}

.sakoda-publication-view .sakoda-piece-mark {
    width: 10px;
    height: 10px;
}

.sakoda-publication-view .sakoda-square-mark {
    border-width: 2px;
}

.sakoda-publication-view .sakoda-cross-mark::before,
.sakoda-publication-view .sakoda-cross-mark::after {
    left: 4px;
    top: -1px;
    width: 2px;
    height: 12px;
}

.sakoda-publication-view .sakoda-piece-label {
    font-size: 0.58rem;
    line-height: 1;
}

.sakoda-publication-legend {
    justify-content: center;
    padding-top: 10px;
}

.sakoda-all-scenarios-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    align-items: stretch;
    gap: 12px;
    width: 100%;
}

.sakoda-gallery-panel {
    display: flex;
    min-width: 0;
    flex-direction: column;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 9px;
    background: #ffffff;
}

.sakoda-gallery-panel-header {
    min-height: 42px;
    margin-bottom: 7px;
}

.sakoda-gallery-panel-kicker {
    margin-bottom: 2px;
    font-size: 0.64rem;
    font-weight: 700;
    line-height: 1.15;
    letter-spacing: 0;
    text-transform: uppercase;
    color: #64748b;
}

.sakoda-gallery-panel h2 {
    margin: 0;
    overflow-wrap: anywhere;
    font-size: 0.98rem;
    font-weight: 750;
    line-height: 1.2;
    letter-spacing: 0;
    color: #172033;
}

.sakoda-gallery-status {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0;
    min-height: 132px;
    margin-top: 8px;
    border-top: 1px solid #dbe2ea;
}

.sakoda-gallery-status-item {
    min-width: 0;
    border-bottom: 1px solid #e5e9ef;
    padding: 6px 5px 7px 0;
}

.sakoda-gallery-status-label {
    display: block;
    margin-bottom: 2px;
    font-size: 0.62rem;
    font-weight: 700;
    line-height: 1.15;
    letter-spacing: 0;
    text-transform: uppercase;
    color: #64748b;
}

.sakoda-gallery-status-value {
    display: block;
    overflow-wrap: anywhere;
    font-size: 0.74rem;
    font-weight: 650;
    line-height: 1.25;
    letter-spacing: 0;
    color: #263445;
}

@media (max-width: 1200px) {
    .sakoda-all-scenarios-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 900px) {
    .sakoda-crossroads-triptych-grid {
        grid-template-columns: 1fr;
    }

    .sakoda-crossroads-triptych-panel {
        width: min(100%, 620px);
        margin-inline: auto;
    }
}

@media (max-width: 700px) {
    .sakoda-shell,
    .sakoda-publication-view {
        padding-inline: 2px;
    }

    .sakoda-publication-heading {
        align-items: start;
        flex-direction: column;
    }

    .sakoda-publication-context {
        justify-content: flex-start;
    }

    .sakoda-all-scenarios-grid {
        grid-template-columns: 1fr;
    }

    .sakoda-piece {
        width: 84%;
        height: 84%;
        gap: 2px;
    }

    .sakoda-piece-mark {
        width: 13px;
        height: 13px;
    }

    .sakoda-square-mark {
        border-width: 2px;
    }

    .sakoda-cross-mark::before,
    .sakoda-cross-mark::after {
        left: 5px;
        height: 16px;
    }

    .sakoda-piece-label {
        font-size: 0.72rem;
    }

    .sakoda-publication-view .sakoda-piece-label {
        font-size: 0.58rem;
    }
}
"""


def scenario_options() -> list[dict[str, str]]:
    return [
        {"name": scenario.name, "label": scenario.display_name}
        for scenario in SCENARIO_LIST
    ]


def convention_options() -> list[dict[str, str]]:
    return [dict(preset) for preset in CONVENTION_PRESETS]


def scenario_label(scenario_name: str) -> str:
    try:
        return SCENARIO_LABELS[scenario_name]
    except KeyError as exc:
        available = ", ".join(SCENARIO_LABELS)
        raise ValueError(
            f"Unknown Sakoda scenario {scenario_name!r}; available: {available}"
        ) from exc


def scenario_name_from_label(label: str) -> str:
    try:
        return SCENARIO_NAMES_BY_LABEL[label]
    except KeyError as exc:
        available = ", ".join(SCENARIO_NAMES_BY_LABEL)
        raise ValueError(
            f"Unknown Sakoda scenario label {label!r}; available: {available}"
        ) from exc


def convention_for_label(label: str) -> dict[str, str]:
    try:
        return dict(CONVENTIONS_BY_LABEL[label])
    except KeyError as exc:
        available = ", ".join(CONVENTIONS_BY_LABEL)
        raise ValueError(
            f"Unknown Sakoda convention label {label!r}; available: {available}"
        ) from exc


def create_model(
    scenario_name: str = DEFAULT_SCENARIO_NAME,
    *,
    seed: int | None = DEFAULT_SEED,
    jump_rule: str = JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
    movement_order: str = MOVEMENT_ORDER_ALL_RANDOM,
) -> SakodaModel:
    return SakodaModel(
        scenario_name,
        seed=seed,
        jump_rule=jump_rule,
        movement_order=movement_order,
    )


def board_cells(model: SakodaModel) -> list[dict[str, Any]]:
    occupied = {piece.position: piece for piece in model.pieces}
    cells: list[dict[str, Any]] = []
    for row in range(1, model.rows + 1):
        for column in range(1, model.columns + 1):
            piece = occupied.get((row, column))
            if piece is None:
                cells.append(
                    {
                        "row": row,
                        "column": column,
                        "group": None,
                        "piece_number": None,
                        "label": "",
                        "symbol": "",
                        "occupied": False,
                    }
                )
            else:
                cells.append(
                    {
                        "row": row,
                        "column": column,
                        "group": piece.group,
                        "piece_number": piece.piece_number,
                        "label": piece.symbol,
                        "symbol": "square" if piece.group == SQUARES else "cross",
                        "occupied": True,
                    }
                )
    return cells


def publication_board_cells(
    snapshot: PublicationBoardSnapshot,
) -> list[dict[str, Any]]:
    occupied = {(piece.row, piece.column): piece for piece in snapshot.pieces}
    cells: list[dict[str, Any]] = []
    for row in range(1, snapshot.rows + 1):
        for column in range(1, snapshot.columns + 1):
            piece = occupied.get((row, column))
            if piece is None:
                cells.append(
                    {
                        "row": row,
                        "column": column,
                        "group": None,
                        "piece_number": None,
                        "label": "",
                        "symbol": "",
                        "occupied": False,
                    }
                )
            else:
                cells.append(
                    {
                        "row": row,
                        "column": column,
                        "group": piece.group,
                        "piece_number": piece.piece_number,
                        "label": piece.label,
                        "symbol": ("square" if piece.group == SQUARES else "cross"),
                        "occupied": True,
                    }
                )
    return cells


def _board_grid_style(rows: int, columns: int) -> str:
    return (
        f"grid-template-columns: repeat({columns}, minmax(0, 1fr)); "
        f"grid-template-rows: repeat({rows}, minmax(0, 1fr));"
    )


def board_grid_style(model: SakodaModel) -> str:
    return _board_grid_style(model.rows, model.columns)


def publication_board_grid_style(snapshot: PublicationBoardSnapshot) -> str:
    return _board_grid_style(snapshot.rows, snapshot.columns)


def latest_metrics(model: SakodaModel) -> dict[str, Any]:
    if not model.metrics_by_cycle:
        return {}
    return dict(model.metrics_by_cycle[-1])


def _format_number(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _status_items(
    model: SakodaModel,
    convention: dict[str, str],
) -> list[tuple[str, str]]:
    metrics = latest_metrics(model)
    return [
        ("Scenario", model.scenario.display_name),
        ("Seed", str(model.seed_value)),
        ("Cycle", str(model.cycle)),
        ("Movement count", str(metrics.get("movement_count", 0))),
        ("Stop reason", model.stop_reason),
        ("Run state", "running" if model.running else "stopped"),
        ("Convention role", convention["role"]),
        ("Jump rule", model.jump_rule),
        ("Movement order", model.movement_order),
    ]


def _metric_items(model: SakodaModel) -> list[tuple[str, str]]:
    metrics = latest_metrics(model)
    keys = [
        "centroid_distance",
        "same_group_adjacent_pairs",
        "mixed_adjacent_pairs",
        "checkerboard_alignment",
        "squares_dispersion",
        "crosses_dispersion",
        "mixed_nearest_neighbor_count",
        "mean_nearest_same_distance",
        "mean_nearest_other_distance",
        "squares_edge_count",
        "crosses_edge_count",
        "squares_corner_count",
        "crosses_corner_count",
    ]
    return [
        (key.replace("_", " ").title(), _format_number(metrics.get(key, "")))
        for key in keys
    ]


def _render_item_grid(items: list[tuple[str, str]], *, classes: list[str]) -> None:
    item_class = classes[0]
    label_class = classes[1]
    value_class = classes[2]
    blocks = []
    for label, value in items:
        blocks.append(
            f'<div class="{escape(item_class)}">'
            f'<div class="{escape(label_class)}">{escape(label)}</div>'
            f'<div class="{escape(value_class)}">{escape(value)}</div>'
            "</div>"
        )
    solara.HTML(tag="div", unsafe_innerHTML="".join(blocks), classes=[classes[3]])


def _piece_html(cell: dict[str, Any]) -> str:
    if not cell["occupied"]:
        return ""
    mark_class = (
        "sakoda-square-mark" if cell["group"] == SQUARES else "sakoda-cross-mark"
    )
    piece_class = (
        "sakoda-square-piece" if cell["group"] == SQUARES else "sakoda-cross-piece"
    )
    title = (
        f"{cell['group']} {cell['piece_number']} "
        f"at row {cell['row']}, column {cell['column']}"
    )
    return (
        f'<div class="sakoda-piece {piece_class}" '
        f'data-piece="{escape(cell["label"])}" '
        f'data-group="{escape(cell["group"])}" title="{escape(title)}">'
        f'<span class="sakoda-piece-mark {mark_class}"></span>'
        f'<span class="sakoda-piece-label">{escape(cell["label"])}</span>'
        "</div>"
    )


def _legend_html(
    *,
    test_id: str | None = None,
    classes: tuple[str, ...] = (),
) -> str:
    test_id_attribute = (
        f' data-testid="{escape(test_id)}"' if test_id is not None else ""
    )
    legend_class = " ".join(("sakoda-legend", *classes))
    return (
        f'<div class="{escape(legend_class)}"{test_id_attribute}>'
        '<span class="sakoda-legend-item">'
        '<span class="sakoda-mini-square"></span>Squares S1-S6</span>'
        '<span class="sakoda-legend-item">'
        '<span class="sakoda-mini-cross"></span>Crosses X1-X6</span>'
        "</div>"
    )


def _board_html(
    cells: list[dict[str, Any]],
    *,
    rows: int,
    columns: int,
    test_id: str | None = None,
    frame_classes: tuple[str, ...] = (),
    board_classes: tuple[str, ...] = (),
    include_legend: bool = True,
    legend_test_id: str | None = None,
) -> str:
    cell_blocks = []
    for cell in cells:
        parity_class = (
            "sakoda-cell-even" if (cell["row"] + cell["column"]) % 2 == 0 else ""
        )
        title = f"Row {cell['row']}, column {cell['column']}"
        cell_blocks.append(
            f'<div class="sakoda-cell {parity_class}" '
            f'data-row="{cell["row"]}" data-column="{cell["column"]}" '
            f'data-occupied="{str(cell["occupied"]).lower()}" '
            f'title="{escape(title)}">'
            f"{_piece_html(cell)}"
            "</div>"
        )

    frame_class = " ".join(("sakoda-board-frame", *frame_classes))
    board_class = " ".join(("sakoda-board", *board_classes))
    test_id_attribute = (
        f' data-testid="{escape(test_id)}"' if test_id is not None else ""
    )
    legend = _legend_html(test_id=legend_test_id) if include_legend else ""
    return (
        f'<div class="{escape(frame_class)}">'
        f'<div class="{escape(board_class)}"{test_id_attribute} '
        f'data-rows="{rows}" data-columns="{columns}" '
        f'style="{escape(_board_grid_style(rows, columns))}">'
        f"{''.join(cell_blocks)}"
        "</div>"
        f"{legend}"
        "</div>"
    )


def _render_board(model: SakodaModel) -> None:
    solara.HTML(
        tag="div",
        unsafe_innerHTML=_board_html(
            board_cells(model),
            rows=model.rows,
            columns=model.columns,
        ),
    )


@solara.component
def board_panel(model: SakodaModel) -> None:
    update_counter.get()
    with solara.Card("Board", margin=0, classes=["sakoda-card"]):
        _render_board(model)


@solara.component
def status_panel(model: SakodaModel, convention: dict[str, str]) -> None:
    update_counter.get()
    convention_class = (
        "sakoda-convention-main"
        if convention["role"] == "main evidence"
        else "sakoda-convention-diagnostic"
    )
    with solara.Card("Run State", margin=0, classes=["sakoda-card", convention_class]):
        _render_item_grid(
            _status_items(model, convention),
            classes=[
                "sakoda-status-item",
                "sakoda-status-label",
                "sakoda-status-value",
                "sakoda-status-grid",
            ],
        )


@solara.component
def metrics_panel(model: SakodaModel) -> None:
    update_counter.get()
    with solara.Card("Metrics", margin=0, classes=["sakoda-card"]):
        _render_item_grid(
            _metric_items(model),
            classes=[
                "sakoda-metric-item",
                "sakoda-metric-label",
                "sakoda-metric-value",
                "sakoda-metrics-grid",
            ],
        )


@solara.component
def scenario_panel(model: SakodaModel) -> None:
    update_counter.get()
    with solara.Card("Scenario", margin=0, classes=["sakoda-card"]):
        _render_item_grid(
            [
                ("Source caption", model.scenario.source_caption),
                ("Squares own", str(model.scenario.squares_own)),
                ("Squares other", str(model.scenario.squares_other)),
                ("Crosses own", str(model.scenario.crosses_own)),
                ("Crosses other", str(model.scenario.crosses_other)),
                ("Max cycles", str(model.max_cycles)),
            ],
            classes=[
                "sakoda-metric-item",
                "sakoda-metric-label",
                "sakoda-metric-value",
                "sakoda-metrics-grid",
            ],
        )


@solara.component
def dashboard_panel(model: SakodaModel, convention: dict[str, str]) -> None:
    update_counter.get()
    with solara.Div(
        classes=["sakoda-full-dashboard"],
        attributes={"data-testid": "sakoda-full-dashboard"},
    ):
        solara.HTML(
            tag="span",
            style="display: none;",
            attributes={
                "data-testid": "sakoda-full-gui-state",
                "data-scenario": model.scenario.name,
                "data-seed": str(model.seed_value),
                "data-cycle": str(model.cycle),
                "data-running": str(model.running).lower(),
                "data-stop-reason": model.stop_reason,
                "data-jump-rule": model.jump_rule,
                "data-movement-order": model.movement_order,
            },
        )
        with solara.Column(gap="12px", classes=["sakoda-shell"]):
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
                    style={"flex": "1.08 1 460px", "min-width": "320px"},
                ):
                    board_panel(model)
                with solara.Column(
                    gap="12px",
                    style={"flex": "0.92 1 360px", "min-width": "300px"},
                ):
                    status_panel(model, convention)
                    scenario_panel(model)
            metrics_panel(model)


def _publication_board_html(
    snapshot: PublicationBoardSnapshot,
    *,
    test_id: str,
) -> str:
    cells = _validated_publication_board_cells(snapshot)
    return _board_html(
        cells,
        rows=snapshot.rows,
        columns=snapshot.columns,
        test_id=test_id,
        frame_classes=("sakoda-publication-board-frame",),
        board_classes=("sakoda-publication-board",),
        include_legend=False,
    )


def _validated_publication_board_cells(
    snapshot: PublicationBoardSnapshot,
) -> list[dict[str, Any]]:
    cells = publication_board_cells(snapshot)
    if (
        snapshot.rows != 8
        or snapshot.columns != 8
        or len(cells) != 64
        or sum(bool(cell["occupied"]) for cell in cells) != 12
    ):
        raise RuntimeError(
            f"Publication board {snapshot.scenario_name!r} cycle "
            f"{snapshot.cycle} must be 8x8 with 12 pieces."
        )
    return cells


def _validate_crossroads_trajectory_contract(
    snapshots: tuple[PublicationBoardSnapshot, ...],
) -> None:
    cycles = tuple(snapshot.cycle for snapshot in snapshots)
    if cycles != CROSSROADS_TRAJECTORY_CYCLES:
        raise ValueError(
            "Crossroads trajectory snapshots must contain cycles "
            f"{CROSSROADS_TRAJECTORY_CYCLES!r}; got {cycles!r}."
        )

    expected_state_by_cycle = {
        0: (True, "running", "running"),
        3: (True, "running", "running"),
        5: (False, "stable", STABLE_MODEL_STOP_REASON),
    }
    for snapshot in snapshots:
        running, stop_state, model_stop_reason = expected_state_by_cycle[snapshot.cycle]
        actual = (
            snapshot.scenario_name,
            snapshot.scenario_label,
            snapshot.seed,
            snapshot.rows,
            snapshot.columns,
            snapshot.jump_rule,
            snapshot.movement_order,
            snapshot.running,
            snapshot.stop_state,
            snapshot.model_stop_reason,
        )
        expected = (
            "crossroads",
            "Crossroads",
            PUBLICATION_SEED,
            8,
            8,
            PUBLICATION_JUMP_RULE,
            PUBLICATION_MOVEMENT_ORDER,
            running,
            stop_state,
            model_stop_reason,
        )
        if actual != expected:
            raise ValueError(
                f"Crossroads trajectory cycle {snapshot.cycle} differs from its "
                f"publication contract: expected {expected!r}, got {actual!r}."
            )
        _validated_publication_board_cells(snapshot)


def crossroads_trajectory_html(
    snapshots: tuple[PublicationBoardSnapshot, ...],
) -> str:
    _validate_crossroads_trajectory_contract(snapshots)
    cycles = tuple(snapshot.cycle for snapshot in snapshots)

    panels = []
    for snapshot in snapshots:
        panels.append(
            '<article class="sakoda-crossroads-triptych-panel" '
            f'data-testid="sakoda-crossroads-triptych-panel-{snapshot.cycle}" '
            f'data-scenario="{escape(snapshot.scenario_name)}" '
            f'data-cycle="{snapshot.cycle}" '
            f'data-stop-state="{escape(snapshot.stop_state)}" '
            f'data-model-stop-reason="{escape(snapshot.model_stop_reason)}">'
            '<div class="sakoda-crossroads-triptych-label" '
            f'data-testid="sakoda-crossroads-triptych-label-{snapshot.cycle}">'
            f"Cycle {snapshot.cycle}</div>"
            f"{_publication_board_html(snapshot, test_id=f'sakoda-crossroads-board-cycle-{snapshot.cycle}')}"
            "</article>"
        )

    cycles_attribute = ",".join(str(cycle) for cycle in cycles)
    legend = _legend_html(
        test_id="sakoda-crossroads-triptych-legend",
        classes=("sakoda-publication-legend",),
    )
    return (
        '<section class="sakoda-publication-view sakoda-crossroads-triptych" '
        f'data-testid="{CROSSROADS_TRIPTYCH_TEST_ID}" '
        'data-view="crossroads-trajectory" data-scenario="crossroads" '
        f'data-seed="{PUBLICATION_SEED}" data-cycles="{cycles_attribute}" '
        f'data-jump-rule="{escape(PUBLICATION_JUMP_RULE)}" '
        f'data-movement-order="{escape(PUBLICATION_MOVEMENT_ORDER)}">'
        '<header class="sakoda-publication-heading">'
        "<h1>Crossroads trajectory</h1>"
        '<div class="sakoda-publication-context">'
        f"<span>Seed {PUBLICATION_SEED}</span>"
        f"<span>{escape(PUBLICATION_JUMP_RULE)}</span>"
        f"<span>{escape(PUBLICATION_MOVEMENT_ORDER)}</span>"
        "</div></header>"
        f'<div class="sakoda-crossroads-triptych-grid">{"".join(panels)}</div>'
        f"{legend}</section>"
    )


def all_scenarios_gallery_html(
    snapshots: tuple[PublicationBoardSnapshot, ...],
) -> str:
    snapshot_by_name = {snapshot.scenario_name: snapshot for snapshot in snapshots}
    expected_names = tuple(spec.name for spec in ALL_SCENARIO_TERMINAL_SPECS)
    if set(snapshot_by_name) != set(expected_names) or len(snapshots) != len(
        expected_names
    ):
        raise ValueError(
            "All-scenarios gallery requires exactly one snapshot for each of: "
            f"{', '.join(expected_names)}."
        )

    panels = []
    for scenario_name in expected_names:
        spec = terminal_spec_for_scenario(scenario_name)
        snapshot = snapshot_by_name[scenario_name]
        actual = (
            snapshot.scenario_label,
            snapshot.seed,
            snapshot.cycle,
            snapshot.stop_state,
            snapshot.model_stop_reason,
            snapshot.running,
            snapshot.jump_rule,
            snapshot.movement_order,
        )
        expected = (
            spec.display_name,
            PUBLICATION_SEED,
            spec.cycle,
            spec.stop_state,
            spec.model_stop_reason,
            False,
            PUBLICATION_JUMP_RULE,
            PUBLICATION_MOVEMENT_ORDER,
        )
        if actual != expected:
            raise ValueError(
                f"Gallery snapshot {scenario_name!r} differs from its display "
                f"contract: expected {expected!r}, got {actual!r}."
            )

        board = _publication_board_html(
            snapshot,
            test_id=f"sakoda-all-scenarios-board-{scenario_name}",
        )
        panels.append(
            '<article class="sakoda-gallery-panel" '
            f'data-testid="sakoda-all-scenarios-panel-{scenario_name}" '
            f'data-scenario="{escape(scenario_name)}" '
            f'data-cycle="{snapshot.cycle}" '
            f'data-seed="{snapshot.seed}" '
            f'data-stop-state="{escape(spec.stop_state)}" '
            f'data-model-stop-reason="{escape(snapshot.model_stop_reason)}" '
            f'data-validation-status="{escape(spec.validation_status)}">'
            '<header class="sakoda-gallery-panel-header">'
            '<div class="sakoda-gallery-panel-kicker">Scenario</div>'
            f"<h2>{escape(spec.display_name)}</h2></header>"
            f"{board}"
            '<div class="sakoda-gallery-status">'
            '<div class="sakoda-gallery-status-item">'
            '<span class="sakoda-gallery-status-label">Cycle</span>'
            f'<span class="sakoda-gallery-status-value">{snapshot.cycle}</span>'
            "</div>"
            '<div class="sakoda-gallery-status-item">'
            '<span class="sakoda-gallery-status-label">Seed</span>'
            f'<span class="sakoda-gallery-status-value">{snapshot.seed}</span>'
            "</div>"
            '<div class="sakoda-gallery-status-item">'
            '<span class="sakoda-gallery-status-label">Stop state</span>'
            f'<span class="sakoda-gallery-status-value">{escape(spec.stop_state)}</span>'
            "</div>"
            '<div class="sakoda-gallery-status-item">'
            '<span class="sakoda-gallery-status-label">Validation status</span>'
            f'<span class="sakoda-gallery-status-value">{escape(spec.validation_status)}</span>'
            "</div></div></article>"
        )

    legend = _legend_html(
        test_id="sakoda-all-scenarios-gallery-legend",
        classes=("sakoda-publication-legend",),
    )
    return (
        '<section class="sakoda-publication-view sakoda-all-scenarios-gallery" '
        f'data-testid="{ALL_SCENARIOS_GALLERY_TEST_ID}" '
        'data-view="all-scenarios" data-layout="2x4" '
        f'data-scenario-count="{len(expected_names)}" '
        f'data-seed="{PUBLICATION_SEED}" '
        f'data-jump-rule="{escape(PUBLICATION_JUMP_RULE)}" '
        f'data-movement-order="{escape(PUBLICATION_MOVEMENT_ORDER)}">'
        '<header class="sakoda-publication-heading">'
        "<h1>All scenarios</h1>"
        '<div class="sakoda-publication-context">'
        f"<span>Seed {PUBLICATION_SEED}</span>"
        f"<span>{escape(PUBLICATION_JUMP_RULE)}</span>"
        f"<span>{escape(PUBLICATION_MOVEMENT_ORDER)}</span>"
        "</div></header>"
        f'<div class="sakoda-all-scenarios-grid">{"".join(panels)}</div>'
        f"{legend}</section>"
    )


@lru_cache(maxsize=1)
def _crossroads_publication_snapshots() -> tuple[PublicationBoardSnapshot, ...]:
    return replay_crossroads_trajectory()


@lru_cache(maxsize=1)
def _all_scenario_publication_snapshots() -> tuple[PublicationBoardSnapshot, ...]:
    return replay_all_scenario_terminals()


@solara.component
def crossroads_trajectory_panel(
    snapshots: tuple[PublicationBoardSnapshot, ...],
) -> None:
    solara.HTML(tag="div", unsafe_innerHTML=crossroads_trajectory_html(snapshots))


@solara.component
def all_scenarios_gallery_panel(
    snapshots: tuple[PublicationBoardSnapshot, ...],
) -> None:
    solara.HTML(tag="div", unsafe_innerHTML=all_scenarios_gallery_html(snapshots))


@solara.component
def page() -> None:
    solara.Style(SAKODA_CSS)
    solara.HTML(
        tag="span",
        style="display: none;",
        classes=["sakoda-full-gui-capture-anchor"],
        attributes={
            "data-testid": FULL_GUI_CAPTURE_ANCHOR_TEST_ID,
            "data-capture-selector": FULL_GUI_CAPTURE_SELECTOR,
        },
    )
    update_counter.get()

    scenario_labels = [option["label"] for option in scenario_options()]
    convention_labels = [option["label"] for option in convention_options()]

    selected_scenario = solara.use_reactive(scenario_label(DEFAULT_SCENARIO_NAME))
    selected_convention = solara.use_reactive(MAIN_CONVENTION_LABEL)
    seed = solara.use_reactive(DEFAULT_SEED)
    playing = solara.use_reactive(False)
    play_interval = solara.use_reactive(DEFAULT_PLAY_INTERVAL_MS)
    view_mode = solara.use_reactive(VIEW_OPTIONS[0])

    initial_model = solara.use_memo(create_model, dependencies=[])
    reactive_model = solara.use_reactive(initial_model)
    trajectory_snapshots = solara.use_memo(
        lambda: (
            _crossroads_publication_snapshots()
            if view_mode.value == VIEW_OPTIONS[1]
            else ()
        ),
        dependencies=[view_mode.value],
    )
    gallery_snapshots = solara.use_memo(
        lambda: (
            _all_scenario_publication_snapshots()
            if view_mode.value == VIEW_OPTIONS[2]
            else ()
        ),
        dependencies=[view_mode.value],
    )

    def current_convention() -> dict[str, str]:
        return convention_for_label(selected_convention.value)

    def build_model(
        *,
        scenario_label_value: str | None = None,
        seed_value: int | None = None,
        convention_label_value: str | None = None,
    ) -> SakodaModel:
        label = scenario_label_value or selected_scenario.value
        convention_label_value = convention_label_value or selected_convention.value
        convention = convention_for_label(convention_label_value)
        return create_model(
            scenario_name_from_label(label),
            seed=seed.value if seed_value is None else seed_value,
            jump_rule=convention["jump_rule"],
            movement_order=convention["movement_order"],
        )

    def reset_model() -> None:
        playing.value = False
        reactive_model.value = build_model()
        force_update()

    def set_scenario(label: str) -> None:
        selected_scenario.value = label
        playing.value = False
        reactive_model.value = build_model(scenario_label_value=label)
        force_update()

    def set_seed(value: int | None) -> None:
        seed_value = DEFAULT_SEED if value is None else int(value)
        seed.value = seed_value
        playing.value = False
        reactive_model.value = build_model(seed_value=seed_value)
        force_update()

    def set_convention(label: str) -> None:
        selected_convention.value = label
        playing.value = False
        reactive_model.value = build_model(convention_label_value=label)
        force_update()

    def set_view_mode(value: str) -> None:
        playing.value = False
        view_mode.set(value)
        force_update()

    def step_model() -> None:
        if not reactive_model.value.running:
            playing.value = False
            force_update()
            return
        reactive_model.value.step()
        if not reactive_model.value.running:
            playing.value = False
        force_update()

    def toggle_playing() -> None:
        if reactive_model.value.running:
            playing.value = not playing.value
            force_update()

    async def run_loop() -> None:
        while playing.value and reactive_model.value.running:
            await asyncio.sleep(play_interval.value / 1000)
            step_model()

    solara.lab.use_task(
        run_loop,
        dependencies=[
            playing.value,
            reactive_model.value.running,
            play_interval.value,
        ],
        prefer_threaded=False,
    )

    convention = current_convention()

    with solara.AppBar():
        solara.AppBarTitle("Sakoda Checkerboard")

    with solara.Sidebar(), solara.Column(gap="10px"):
        with solara.Card(
            "Controls",
            classes=["sakoda-sidebar-card", "sakoda-controls"],
        ):
            solara.ToggleButtonsSingle(
                value=view_mode.value,
                values=list(VIEW_OPTIONS),
                on_value=set_view_mode,
                dense=True,
                mandatory=True,
                classes=["sakoda-mode-toggle"],
            )
            solara.Select(
                "Scenario",
                values=scenario_labels,
                value=selected_scenario.value,
                on_value=set_scenario,
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
                "Convention",
                values=convention_labels,
                value=selected_convention.value,
                on_value=set_convention,
                dense=True,
                classes=["sakoda-convention-select"],
            )
            solara.SliderInt(
                "Run interval (ms)",
                value=play_interval,
                on_value=lambda value: play_interval.set(value),
                min=50,
                max=1000,
                step=50,
            )
            with solara.Row(gap="8px", classes=["sakoda-control-actions"]):
                solara.Button(label="Reset", color="primary", on_click=reset_model)
                solara.Button(
                    label="Pause" if playing.value else "Run",
                    color="primary",
                    on_click=toggle_playing,
                    disabled=not reactive_model.value.running,
                )
                solara.Button(
                    label="Step",
                    color="primary",
                    on_click=step_model,
                    disabled=playing.value or not reactive_model.value.running,
                )

    if view_mode.value == VIEW_OPTIONS[1]:
        crossroads_trajectory_panel(trajectory_snapshots)
    elif view_mode.value == VIEW_OPTIONS[2]:
        all_scenarios_gallery_panel(gallery_snapshots)
    else:
        dashboard_panel(reactive_model.value, convention)


__all__ = [
    "ALL_SCENARIOS_GALLERY_TEST_ID",
    "CONTROLS_CAPTURE_SELECTOR",
    "CROSSROADS_TRIPTYCH_TEST_ID",
    "DEFAULT_PLAY_INTERVAL_MS",
    "DEFAULT_SCENARIO_NAME",
    "DEFAULT_SEED",
    "FULL_GUI_CAPTURE_ANCHOR_TEST_ID",
    "FULL_GUI_CAPTURE_SELECTOR",
    "MAIN_CONVENTION_LABEL",
    "VIEW_OPTIONS",
    "all_scenarios_gallery_html",
    "board_cells",
    "board_grid_style",
    "convention_for_label",
    "convention_options",
    "create_model",
    "crossroads_trajectory_html",
    "latest_metrics",
    "page",
    "publication_board_cells",
    "publication_board_grid_style",
    "scenario_label",
    "scenario_name_from_label",
    "scenario_options",
]
