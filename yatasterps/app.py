from __future__ import annotations

from html import escape

import solara
from matplotlib.figure import Figure
from mesa.visualization import make_plot_component, make_space_component
from mesa.visualization.solara_viz import ModelController, ModelCreator, ShowSteps
from mesa.visualization.utils import update_counter

from yatasterps.agents import YouthAgent
from yatasterps.config import (
    AFTER_SCHOOL_HOURS,
    DEFAULT_MAX_TICKS,
    DEFAULT_SEED,
    DEFAULT_YOUTH_COUNT,
    EVENING_HOURS,
    PARAMETER_SPECS,
    PRO_OPP_LAYER_NAME,
    REGION_COLORS,
    REGION_LAYER_NAME,
    RISK_OPP_LAYER_NAME,
    SCHOOL_HOURS,
    WORLD_BOUNDS,
    YOUTH_COLORS,
    grid_to_netlogo,
)
from yatasterps.model import YaTASERPSModel

RISK_DISTRIBUTION_COLOR = YOUTH_COLORS["antisocial"]
PRO_DISTRIBUTION_COLOR = "#277da1"
# The literal v1.0.0 NetLogo headline plot includes antisocial, prosocial, and equal pens.
HEADLINE_COLORS = {
    "Percent Antisocial": YOUTH_COLORS["antisocial"],
    "Percent Prosocial": YOUTH_COLORS["prosocial"],
    "Percent Equal": "#6c757d",
}

DASHBOARD_CSS = """
.dashboard-shell {
    width: 100%;
}

.dashboard-card .v-card__title {
    padding-bottom: 0;
}

.dashboard-card .v-card__text {
    padding-top: 12px;
}

.dashboard-figure-card .v-card__text {
    padding-top: 8px;
}

.dashboard-figure-card img {
    display: block;
    width: 100%;
    height: auto;
}

.stat-strip {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
}

.stat-chip {
    flex: 1 1 132px;
    min-width: 132px;
    padding: 10px 12px;
    border: 1px solid #d9e2ec;
    border-radius: 12px;
    background: #f8fbff;
}

.stat-chip-label {
    margin-bottom: 4px;
    font-size: 0.76rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #52606d;
}

.stat-chip-value {
    font-size: 1.35rem;
    font-weight: 700;
    line-height: 1.2;
    white-space: nowrap;
    color: #102a43;
}

.monitor-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
}

.monitor-item {
    min-height: 72px;
    padding: 10px 12px;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    background: #f8fafc;
}

.monitor-label {
    margin-bottom: 6px;
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #52606d;
}

.monitor-value {
    font-size: 1.05rem;
    font-weight: 600;
    line-height: 1.3;
    color: #102a43;
}

.monitor-note {
    margin-top: 12px;
    font-size: 0.92rem;
    line-height: 1.45;
    color: #52606d;
}

.help-copy p {
    margin: 0 0 8px 0;
}

.help-copy ul {
    margin: 0;
    padding-left: 18px;
}
"""


def _current_stage_label(model: YaTASERPSModel) -> str:
    if model.current_stage == "ready":
        return "Ready"
    return f"{model.current_stage} ({model.current_substep})"


def _latest_trace_text(model: YaTASERPSModel) -> str:
    return model.last_pipeline_trace_text or "Not stepped yet"


def _render_stat_strip(items: list[tuple[str, str]]) -> None:
    chips = "".join(
        (
            '<div class="stat-chip">'
            f'<div class="stat-chip-label">{escape(label)}</div>'
            f'<div class="stat-chip-value">{escape(value)}</div>'
            "</div>"
        )
        for label, value in items
    )
    solara.HTML(tag="div", unsafe_innerHTML=chips, classes=["stat-strip"])


def _render_monitor_grid(items: list[tuple[str, str]]) -> None:
    blocks = "".join(
        (
            '<div class="monitor-item">'
            f'<div class="monitor-label">{escape(label)}</div>'
            f'<div class="monitor-value">{escape(value)}</div>'
            "</div>"
        )
        for label, value in items
    )
    solara.HTML(tag="div", unsafe_innerHTML=blocks, classes=["monitor-grid"])


def _render_notes(lines: list[str]) -> None:
    note_html = "".join(f"<div>{escape(line)}</div>" for line in lines if line)
    if note_html:
        solara.HTML(tag="div", unsafe_innerHTML=note_html, classes=["monitor-note"])


@solara.component
def monitor_card(
    title: str, items: list[tuple[str, str]], *, notes: list[str] | None = None
):
    with solara.Card(title, margin=0, classes=["dashboard-card"]):
        _render_monitor_grid(items)
        if notes:
            _render_notes(notes)


def _build_histogram_figure(
    series: list[tuple[str, list[float], str]],
    *,
    x_label: str,
    y_label: str = "Frequency",
    value_range: tuple[float, float] | None = (0.0, 1.0),
) -> Figure:
    fig = Figure(figsize=(5.4, 3.2))
    ax = fig.subplots()
    has_data = any(values for _, values, _ in series)

    if has_data:
        for label, values, color in series:
            if not values:
                continue
            ax.hist(
                values,
                bins=20,
                range=value_range,
                color=color,
                alpha=0.45,
                edgecolor=color,
                linewidth=1.0,
                label=label,
            )
        if value_range is not None:
            ax.set_xlim(*value_range)
        ax.legend(loc="upper right", fontsize=8)
    else:
        ax.text(
            0.5,
            0.5,
            "No data available",
            ha="center",
            va="center",
            transform=ax.transAxes,
            color="#52606d",
        )

    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.grid(axis="y", alpha=0.2)
    return fig


@solara.component
def histogram_card(
    title: str,
    series: list[tuple[str, list[float], str]],
    *,
    x_label: str,
    y_label: str = "Frequency",
    value_range: tuple[float, float] | None = (0.0, 1.0),
):
    fig = _build_histogram_figure(
        series,
        x_label=x_label,
        y_label=y_label,
        value_range=value_range,
    )
    with solara.Card(
        title, margin=0, classes=["dashboard-card", "dashboard-figure-card"]
    ):
        solara.FigureMatplotlib(fig, format="png", bbox_inches="tight")


def _agent_position_text(agent: YouthAgent) -> str:
    if agent.pos is None:
        return "unplaced"
    x, y = grid_to_netlogo(*agent.pos)
    return f"({x}, {y})"


@solara.component
def agent_inspector(model: YaTASERPSModel):
    update_counter.get()
    agents = model.youths
    selected_index_state, set_selected_index = solara.use_state(0)

    with solara.Column(gap="12px"):
        if not agents:
            solara.Text("No youths are present in this run.")
            return

        selected_index = min(selected_index_state, len(agents) - 1)
        if len(agents) > 1:
            solara.SliderInt(
                label="Youth index",
                value=selected_index,
                on_value=set_selected_index,
                min=0,
                max=len(agents) - 1,
                step=1,
            )

        agent = agents[selected_index]
        _render_monitor_grid(
            [
                ("Type", "Youth"),
                ("Unique ID", str(agent.unique_id)),
                ("NetLogo position", _agent_position_text(agent)),
                ("Band", agent.location_band),
                ("Visual color", agent.visual_color),
                ("Prosocial tally", f"{agent.prosocial:.3f}"),
                ("Antisocial tally", f"{agent.antisocial:.3f}"),
                ("Family risk", f"{agent.family_risk:.3f}"),
                ("Family promotive", f"{agent.family_pro:.3f}"),
                ("Individual risk", f"{agent.individual_risk:.3f}"),
                ("Individual promotive", f"{agent.individual_pro:.3f}"),
            ]
        )


@solara.component
def dashboard_panel(model: YaTASERPSModel):
    update_counter.get()

    with solara.Column(
        gap="16px",
        style={"padding": "8px 8px 18px 8px", "width": "100%"},
        classes=["dashboard-shell"],
    ):
        with solara.Card("Live Overview", margin=0, classes=["dashboard-card"]):
            _render_stat_strip(
                [
                    ("Day", str(model.day)),
                    ("Stage", _current_stage_label(model)),
                    ("Mean Prosocial", f"{model.mean_prosocial:.2f}"),
                    ("Mean Antisocial", f"{model.mean_antisocial:.2f}"),
                    ("% Antisocial", f"{model.percent_antisocial_share * 100:.1f}%"),
                ]
            )

        with solara.Row(
            gap="16px",
            style={"align-items": "stretch", "flex-wrap": "wrap", "width": "100%"},
        ):
            with solara.Column(
                gap="16px",
                style={"flex": "0.95 1 360px", "min-width": "360px"},
            ):
                with solara.Card(
                    margin=0, classes=["dashboard-card", "dashboard-figure-card"]
                ):
                    space_component(model)

            with solara.Column(
                gap="16px",
                style={"flex": "1.25 1 460px", "min-width": "420px"},
            ):
                with solara.Card(
                    margin=0, classes=["dashboard-card", "dashboard-figure-card"]
                ):
                    diagnostic_plot(model)

        with solara.Row(
            gap="16px",
            style={"align-items": "stretch", "flex-wrap": "wrap", "width": "100%"},
        ):
            with solara.Column(
                gap="16px", style={"flex": "1 1 280px", "min-width": "260px"}
            ):
                monitor_card(
                    "Core Monitors",
                    [
                        ("Mean prosocial", f"{model.mean_prosocial:.3f}"),
                        ("Mean antisocial", f"{model.mean_antisocial:.3f}"),
                        (
                            "% antisocial",
                            f"{model.percent_antisocial_share * 100:.1f}%",
                        ),
                    ],
                )

            with solara.Column(
                gap="16px", style={"flex": "1 1 280px", "min-width": "260px"}
            ):
                monitor_card(
                    "Run Details",
                    [
                        ("Mesa step count", str(model.steps)),
                        ("Current stage", model.current_stage),
                        ("Current substep", str(model.current_substep)),
                        ("Pipeline order", model.pipeline_definition_text),
                    ],
                    notes=[
                        f"Latest trace: {_latest_trace_text(model)}",
                        (
                            f"Phase timings: school {SCHOOL_HOURS}, "
                            f"after-school {AFTER_SCHOOL_HOURS}, evening {EVENING_HOURS}"
                        ),
                    ],
                )

            with solara.Column(
                gap="16px", style={"flex": "1 1 280px", "min-width": "260px"}
            ):
                monitor_card(
                    "Space Snapshot",
                    [
                        ("Youth count", str(len(model.youths))),
                        ("Youths at home", str(model.youths_at_home_count)),
                        (
                            "Youths in neighborhood",
                            str(model.youths_in_neighborhood_count),
                        ),
                        ("Youths at school", str(model.youths_at_school_count)),
                    ],
                )

        with solara.Details("Agent Inspector", expand=False):
            with solara.Column(gap="12px", style={"padding-top": "8px"}):
                agent_inspector(model)

        with solara.Details("Distribution Charts", expand=False):
            with solara.Column(gap="16px", style={"padding-top": "8px"}):
                with solara.Row(
                    gap="16px",
                    style={
                        "align-items": "stretch",
                        "flex-wrap": "wrap",
                        "width": "100%",
                    },
                ):
                    with solara.Column(
                        gap="16px",
                        style={"flex": "1 1 420px", "min-width": "360px"},
                    ):
                        histogram_card(
                            "Family Risk",
                            [
                                (
                                    "Family risk",
                                    model.youth_attribute_values("family_risk"),
                                    RISK_DISTRIBUTION_COLOR,
                                ),
                            ],
                            x_label="Score",
                        )

                    with solara.Column(
                        gap="16px",
                        style={"flex": "1 1 420px", "min-width": "360px"},
                    ):
                        histogram_card(
                            "Family Promotive",
                            [
                                (
                                    "Family promotive",
                                    model.youth_attribute_values("family_pro"),
                                    PRO_DISTRIBUTION_COLOR,
                                ),
                            ],
                            x_label="Score",
                        )

                with solara.Row(
                    gap="16px",
                    style={
                        "align-items": "stretch",
                        "flex-wrap": "wrap",
                        "width": "100%",
                    },
                ):
                    with solara.Column(
                        gap="16px",
                        style={"flex": "1 1 420px", "min-width": "360px"},
                    ):
                        histogram_card(
                            "School Risk",
                            [
                                (
                                    "School risk",
                                    model.band_layer_values(
                                        "school", RISK_OPP_LAYER_NAME
                                    ),
                                    RISK_DISTRIBUTION_COLOR,
                                ),
                            ],
                            x_label="Opportunity score",
                        )

                    with solara.Column(
                        gap="16px",
                        style={"flex": "1 1 420px", "min-width": "360px"},
                    ):
                        histogram_card(
                            "School Promotive",
                            [
                                (
                                    "School promotive",
                                    model.band_layer_values(
                                        "school", PRO_OPP_LAYER_NAME
                                    ),
                                    PRO_DISTRIBUTION_COLOR,
                                ),
                            ],
                            x_label="Opportunity score",
                        )

                with solara.Row(
                    gap="16px",
                    style={
                        "align-items": "stretch",
                        "flex-wrap": "wrap",
                        "width": "100%",
                    },
                ):
                    with solara.Column(
                        gap="16px",
                        style={"flex": "1 1 420px", "min-width": "360px"},
                    ):
                        histogram_card(
                            "Neighborhood Risk",
                            [
                                (
                                    "Neighborhood risk",
                                    model.band_layer_values(
                                        "neighborhood", RISK_OPP_LAYER_NAME
                                    ),
                                    RISK_DISTRIBUTION_COLOR,
                                ),
                            ],
                            x_label="Opportunity score",
                        )

                    with solara.Column(
                        gap="16px",
                        style={"flex": "1 1 420px", "min-width": "360px"},
                    ):
                        histogram_card(
                            "Neighborhood Promotive",
                            [
                                (
                                    "Neighborhood promotive",
                                    model.band_layer_values(
                                        "neighborhood", PRO_OPP_LAYER_NAME
                                    ),
                                    PRO_DISTRIBUTION_COLOR,
                                ),
                            ],
                            x_label="Opportunity score",
                        )

                with solara.Row(
                    gap="16px",
                    style={
                        "align-items": "stretch",
                        "flex-wrap": "wrap",
                        "width": "100%",
                    },
                ):
                    with solara.Column(
                        gap="16px",
                        style={"flex": "1 1 420px", "min-width": "360px"},
                    ):
                        histogram_card(
                            "risk and promotive scores",
                            [
                                (
                                    "Individual risk",
                                    model.youth_attribute_values("individual_risk"),
                                    RISK_DISTRIBUTION_COLOR,
                                ),
                                (
                                    "Individual promotive",
                                    model.youth_attribute_values("individual_pro"),
                                    PRO_DISTRIBUTION_COLOR,
                                ),
                            ],
                            x_label="Score",
                        )

        with solara.Details("Display Help", expand=False):
            solara.HTML(
                tag="div",
                classes=["help-copy"],
                unsafe_innerHTML=(
                    "<p>This Phase 4 view focuses on the youth-only v1.0.0 reporting surface.</p>"
                    "<ul>"
                    f"<li>Band colors: home {escape(REGION_COLORS['home'])}, "
                    f"neighborhood {escape(REGION_COLORS['neighborhood'])}, "
                    f"school {escape(REGION_COLORS['school'])}</li>"
                    "<li>The six sliders are the only model controls</li>"
                    "<li>The Family Risk chart intentionally uses actual family-risk values rather than repeating family-promotive values</li>"
                    "</ul>"
                ),
            )


MODEL_PARAMS = {
    "risk_level": {
        "type": "SliderInt",
        "label": "risk-level",
        "value": PARAMETER_SPECS["risk_level"].default,
        "min": PARAMETER_SPECS["risk_level"].minimum,
        "max": PARAMETER_SPECS["risk_level"].maximum,
        "step": PARAMETER_SPECS["risk_level"].step,
    },
    "promotive_level": {
        "type": "SliderInt",
        "label": "promotive-level",
        "value": PARAMETER_SPECS["promotive_level"].default,
        "min": PARAMETER_SPECS["promotive_level"].minimum,
        "max": PARAMETER_SPECS["promotive_level"].maximum,
        "step": PARAMETER_SPECS["promotive_level"].step,
    },
    "schools_risk": {
        "type": "SliderInt",
        "label": "schools-risk",
        "value": PARAMETER_SPECS["schools_risk"].default,
        "min": PARAMETER_SPECS["schools_risk"].minimum,
        "max": PARAMETER_SPECS["schools_risk"].maximum,
        "step": PARAMETER_SPECS["schools_risk"].step,
    },
    "schools_promotive": {
        "type": "SliderInt",
        "label": "schools-promotive",
        "value": PARAMETER_SPECS["schools_promotive"].default,
        "min": PARAMETER_SPECS["schools_promotive"].minimum,
        "max": PARAMETER_SPECS["schools_promotive"].maximum,
        "step": PARAMETER_SPECS["schools_promotive"].step,
    },
    "neighborhood_risk": {
        "type": "SliderInt",
        "label": "neighborhood-risk",
        "value": PARAMETER_SPECS["neighborhood_risk"].default,
        "min": PARAMETER_SPECS["neighborhood_risk"].minimum,
        "max": PARAMETER_SPECS["neighborhood_risk"].maximum,
        "step": PARAMETER_SPECS["neighborhood_risk"].step,
    },
    "neighborhood_promotive": {
        "type": "SliderInt",
        "label": "neighborhood-promotive",
        "value": PARAMETER_SPECS["neighborhood_promotive"].default,
        "min": PARAMETER_SPECS["neighborhood_promotive"].minimum,
        "max": PARAMETER_SPECS["neighborhood_promotive"].maximum,
        "step": PARAMETER_SPECS["neighborhood_promotive"].step,
    },
}


def agent_portrayal(agent: YouthAgent) -> dict[str, object]:
    return {
        "color": agent.visual_color,
        "size": agent.size,
        "marker": agent.marker,
        "edgecolors": "#111111",
        "linewidths": 0.5,
        "zorder": 2,
    }


def post_process_space(ax) -> None:
    width = WORLD_BOUNDS.max_x - WORLD_BOUNDS.min_x + 1
    ax.set_title("Spatial Layout")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.axhline(4.5, color="#1f2933", linewidth=1, alpha=0.4)
    ax.axhline(35.5, color="#1f2933", linewidth=1, alpha=0.4)
    ax.text(width / 2, 2, "Home", ha="center", va="center", color="#102a43")
    ax.text(width / 2, 20, "Neighborhood", ha="center", va="center", color="#243b0b")
    ax.text(width / 2, 38, "School", ha="center", va="center", color="#4a2c17")


def post_process_plot(ax) -> None:
    ax.set_title("% more pro- or anti-social experiences")
    ax.set_ylabel("Share of Youth")
    ax.set_ylim(0, 1)


space_component = make_space_component(
    agent_portrayal,
    propertylayer_portrayal={
        REGION_LAYER_NAME: {
            "colormap": [
                REGION_COLORS["home"],
                REGION_COLORS["neighborhood"],
                REGION_COLORS["school"],
            ],
            "alpha": 0.45,
            "vmin": 0,
            "vmax": 2,
            "colorbar": False,
        }
    },
    post_process=post_process_space,
)

diagnostic_plot = make_plot_component(HEADLINE_COLORS, post_process=post_process_plot)


def _build_default_model() -> YaTASERPSModel:
    return YaTASERPSModel(
        num_youth=DEFAULT_YOUTH_COUNT,
        max_ticks=DEFAULT_MAX_TICKS,
        seed=DEFAULT_SEED,
    )


@solara.component
def page():
    solara.Style(DASHBOARD_CSS)

    initial_model = solara.use_memo(_build_default_model, dependencies=[])
    reactive_model = solara.use_reactive(initial_model)
    reactive_model_parameters = solara.use_reactive({})
    reactive_play_interval = solara.use_reactive(100)
    reactive_render_interval = solara.use_reactive(1)

    with solara.AppBar():
        solara.AppBarTitle("Ya-TASERPS")

    with solara.Sidebar(), solara.Column():
        with solara.Card("Controls"):
            solara.SliderInt(
                label="Play Interval (ms)",
                value=reactive_play_interval,
                on_value=lambda value: reactive_play_interval.set(value),
                min=1,
                max=500,
                step=10,
            )
            solara.SliderInt(
                label="Render Interval (steps)",
                value=reactive_render_interval,
                on_value=lambda value: reactive_render_interval.set(value),
                min=1,
                max=100,
                step=2,
            )
            ModelController(
                reactive_model,
                model_parameters=reactive_model_parameters,
                play_interval=reactive_play_interval,
                render_interval=reactive_render_interval,
            )

        with solara.Card("Model Parameters"):
            ModelCreator(
                reactive_model,
                MODEL_PARAMS,
                model_parameters=reactive_model_parameters,
            )

        with solara.Card("Information"):
            ShowSteps(reactive_model.value)

    dashboard_panel(reactive_model.value)
