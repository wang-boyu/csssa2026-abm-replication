from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

NetLogoValue = bool | int | float | str
MetricCategory = Literal["primary", "supporting", "raw_only"]


@dataclass(frozen=True, slots=True)
class CoordinateRange:
    x_min: int
    x_max: int
    y_min: int
    y_max: int


@dataclass(frozen=True, slots=True)
class ParameterCrosswalkEntry:
    netlogo_name: str
    mesa_alias: str
    default_value: NetLogoValue
    selected_values: tuple[NetLogoValue, ...]
    role: str


@dataclass(frozen=True, slots=True)
class MetricCrosswalkEntry:
    netlogo_name: str
    mesa_alias: str
    category: MetricCategory
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ParameterCombination:
    label: str
    values: tuple[tuple[str, NetLogoValue], ...]

    @property
    def parameters(self) -> dict[str, NetLogoValue]:
        return dict(self.values)

    @property
    def parameter_values(self) -> dict[str, NetLogoValue]:
        return self.parameters


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    name: str
    reference_name: str
    setup_command: str
    go_command: str
    simulation_runtime: int
    repetitions: int
    run_metrics_every_step: bool
    step_min: int
    step_max: int
    rows_per_run: int
    expected_runs: int
    expected_rows: int
    raw_output_columns: int
    reference_setup_file: Path
    reference_raw_table: Path
    parameter_combinations: tuple[ParameterCombination, ...]


PROVENANCE_NETLOGO_SOURCE: Final[Path] = Path(
    "references/slumulation/Slumulation_OriginalModel_NetLogo4_2.nlogo"
)
EXECUTION_REFERENCE_NETLOGO_SOURCE: Final[Path] = Path(
    "references/slumulation/Slumulation_NetLogo6_1.nlogo"
)
NETLOGO_RESULTS_DIR: Final[Path] = Path("results/slumulation/netlogo")

PROVENANCE_NETLOGO_SOURCE_SHA256: Final[str] = (
    "260d34047de19fcf65c246d54e4193f8870c31042c1fff2db25475f5ab76f1e4"
)
EXECUTION_REFERENCE_NETLOGO_SOURCE_SHA256: Final[str] = (
    "2f75d39b6c701f7e3bfe4026006634f437253f6becb4428c7040f8239e7e362a"
)
NETLOGO_SOURCE_SHA256: Final[dict[Path, str]] = {
    PROVENANCE_NETLOGO_SOURCE: PROVENANCE_NETLOGO_SOURCE_SHA256,
    EXECUTION_REFERENCE_NETLOGO_SOURCE: EXECUTION_REFERENCE_NETLOGO_SOURCE_SHA256,
}

WORLD_X_MIN: Final[int] = -25
WORLD_X_MAX: Final[int] = 25
WORLD_Y_MIN: Final[int] = -25
WORLD_Y_MAX: Final[int] = 25
WORLD_WIDTH: Final[int] = 51
WORLD_HEIGHT: Final[int] = 51
WORLD_PATCH_COUNT: Final[int] = WORLD_WIDTH * WORLD_HEIGHT
CENTRAL_WARD: Final[int] = 5
PERIPHERAL_WARDS: Final[tuple[int, ...]] = (1, 2, 3, 4, 6, 7, 8, 9)

WARD_COORDINATE_RANGES: Final[dict[int, CoordinateRange]] = {
    1: CoordinateRange(x_min=-25, x_max=-9, y_min=-25, y_max=-9),
    2: CoordinateRange(x_min=-8, x_max=8, y_min=-25, y_max=-9),
    3: CoordinateRange(x_min=9, x_max=25, y_min=-25, y_max=-9),
    4: CoordinateRange(x_min=-25, x_max=-9, y_min=-8, y_max=8),
    5: CoordinateRange(x_min=-8, x_max=8, y_min=-8, y_max=8),
    6: CoordinateRange(x_min=9, x_max=25, y_min=-8, y_max=8),
    7: CoordinateRange(x_min=-25, x_max=-9, y_min=9, y_max=25),
    8: CoordinateRange(x_min=-8, x_max=8, y_min=9, y_max=25),
    9: CoordinateRange(x_min=9, x_max=25, y_min=9, y_max=25),
}
WORLD_BOUNDS: Final[tuple[int, int, int, int]] = (
    WORLD_X_MIN,
    WORLD_X_MAX,
    WORLD_Y_MIN,
    WORLD_Y_MAX,
)
WARD_BOUNDS: Final[dict[int, CoordinateRange]] = WARD_COORDINATE_RANGES
DEFAULT_MAX_SEARCH_ATTEMPTS: Final[int] = 100_000

SETUP_COMMAND: Final[str] = "setup"
GO_COMMAND: Final[str] = "Slumulate"
SIMULATION_RUNTIME: Final[int] = 50
REFERENCE_REPETITIONS: Final[int] = 30
STEP_MIN: Final[int] = 0
STEP_MAX: Final[int] = 50
ROWS_PER_RUN: Final[int] = 51
RAW_OUTPUT_COLUMNS: Final[int] = 32

PARAMETER_FIELD_ORDER: Final[tuple[str, ...]] = (
    "staying-power",
    "percent-inappropriate-land",
    "informalityindex",
    "percent-prime-land",
    "initialcitylimit",
    "popgrowthrate",
    "SimulationRuntime",
    "Politics",
    "Develop",
    "price-sensitivity",
    "diffusion-rate",
    "economicgrowthrate",
    "initialinequality",
)

PARAMETER_CROSSWALK: Final[tuple[ParameterCrosswalkEntry, ...]] = (
    ParameterCrosswalkEntry(
        netlogo_name="staying-power",
        mesa_alias="staying_power",
        default_value=0.3,
        selected_values=(0.3,),
        role="Search trigger tolerance after rent becomes unaffordable.",
    ),
    ParameterCrosswalkEntry(
        netlogo_name="percent-inappropriate-land",
        mesa_alias="percent_inappropriate_land",
        default_value=10,
        selected_values=(10,),
        role="Initial low-rent or inappropriate land share in the city core.",
    ),
    ParameterCrosswalkEntry(
        netlogo_name="informalityindex",
        mesa_alias="informality_index",
        default_value=0.7,
        selected_values=(0.7,),
        role="Probability that a household is informal in selected experiments.",
    ),
    ParameterCrosswalkEntry(
        netlogo_name="percent-prime-land",
        mesa_alias="percent_prime_land",
        default_value=10,
        selected_values=(10,),
        role="Initial high-rent or prime land share in the city core.",
    ),
    ParameterCrosswalkEntry(
        netlogo_name="initialcitylimit",
        mesa_alias="initial_city_limit",
        default_value=9,
        selected_values=(9,),
        role="Initial city-core extent for selected experiments.",
    ),
    ParameterCrosswalkEntry(
        netlogo_name="popgrowthrate",
        mesa_alias="population_growth_rate",
        default_value=3,
        selected_values=(2, 3, 4),
        role="New household creation rate.",
    ),
    ParameterCrosswalkEntry(
        netlogo_name="SimulationRuntime",
        mesa_alias="simulation_runtime",
        default_value=SIMULATION_RUNTIME,
        selected_values=(SIMULATION_RUNTIME,),
        role="Source stopping horizon.",
    ),
    ParameterCrosswalkEntry(
        netlogo_name="Politics",
        mesa_alias="politics",
        default_value=True,
        selected_values=(True, False),
        role="Enables ward slum-share rent adjustment.",
    ),
    ParameterCrosswalkEntry(
        netlogo_name="Develop",
        mesa_alias="develop",
        default_value=True,
        selected_values=(True, False),
        role="Enables developer creation.",
    ),
    ParameterCrosswalkEntry(
        netlogo_name="price-sensitivity",
        mesa_alias="price_sensitivity",
        default_value=0.1,
        selected_values=(0.1,),
        role="Sharing willingness threshold.",
    ),
    ParameterCrosswalkEntry(
        netlogo_name="diffusion-rate",
        mesa_alias="diffusion_rate",
        default_value=0.03,
        selected_values=(0.03,),
        role="Rent diffusion rate.",
    ),
    ParameterCrosswalkEntry(
        netlogo_name="economicgrowthrate",
        mesa_alias="economic_growth_rate",
        default_value=2,
        selected_values=(2,),
        role="Household income, rent, and city-income growth.",
    ),
    ParameterCrosswalkEntry(
        netlogo_name="initialinequality",
        mesa_alias="initial_inequality",
        default_value=10,
        selected_values=(10,),
        role="Sets min-rent from max-rent divided by initial inequality.",
    ),
)

PARAMETER_CROSSWALK_BY_NETLOGO_NAME: Final[dict[str, ParameterCrosswalkEntry]] = {
    entry.netlogo_name: entry for entry in PARAMETER_CROSSWALK
}
PARAMETER_CROSSWALK_BY_MESA_ALIAS: Final[dict[str, ParameterCrosswalkEntry]] = {
    entry.mesa_alias: entry for entry in PARAMETER_CROSSWALK
}

BASELINE_PARAMETER_VALUES: Final[tuple[tuple[str, NetLogoValue], ...]] = (
    ("staying-power", 0.3),
    ("percent-inappropriate-land", 10),
    ("informalityindex", 0.7),
    ("percent-prime-land", 10),
    ("initialcitylimit", 9),
    ("popgrowthrate", 3),
    ("SimulationRuntime", SIMULATION_RUNTIME),
    ("Politics", True),
    ("Develop", True),
    ("price-sensitivity", 0.1),
    ("diffusion-rate", 0.03),
    ("economicgrowthrate", 2),
    ("initialinequality", 10),
)
POPGROWTHRATE_2_PARAMETER_VALUES: Final[tuple[tuple[str, NetLogoValue], ...]] = (
    ("staying-power", 0.3),
    ("percent-inappropriate-land", 10),
    ("informalityindex", 0.7),
    ("percent-prime-land", 10),
    ("initialcitylimit", 9),
    ("popgrowthrate", 2),
    ("SimulationRuntime", SIMULATION_RUNTIME),
    ("Politics", True),
    ("Develop", True),
    ("price-sensitivity", 0.1),
    ("diffusion-rate", 0.03),
    ("economicgrowthrate", 2),
    ("initialinequality", 10),
)
POPGROWTHRATE_3_PARAMETER_VALUES: Final[tuple[tuple[str, NetLogoValue], ...]] = (
    ("staying-power", 0.3),
    ("percent-inappropriate-land", 10),
    ("informalityindex", 0.7),
    ("percent-prime-land", 10),
    ("initialcitylimit", 9),
    ("popgrowthrate", 3),
    ("SimulationRuntime", SIMULATION_RUNTIME),
    ("Politics", True),
    ("Develop", True),
    ("price-sensitivity", 0.1),
    ("diffusion-rate", 0.03),
    ("economicgrowthrate", 2),
    ("initialinequality", 10),
)
POPGROWTHRATE_4_PARAMETER_VALUES: Final[tuple[tuple[str, NetLogoValue], ...]] = (
    ("staying-power", 0.3),
    ("percent-inappropriate-land", 10),
    ("informalityindex", 0.7),
    ("percent-prime-land", 10),
    ("initialcitylimit", 9),
    ("popgrowthrate", 4),
    ("SimulationRuntime", SIMULATION_RUNTIME),
    ("Politics", True),
    ("Develop", True),
    ("price-sensitivity", 0.1),
    ("diffusion-rate", 0.03),
    ("economicgrowthrate", 2),
    ("initialinequality", 10),
)
POLITICS_TRUE_DEVELOP_TRUE_PARAMETER_VALUES: Final[
    tuple[tuple[str, NetLogoValue], ...]
] = BASELINE_PARAMETER_VALUES
POLITICS_TRUE_DEVELOP_FALSE_PARAMETER_VALUES: Final[
    tuple[tuple[str, NetLogoValue], ...]
] = (
    ("staying-power", 0.3),
    ("percent-inappropriate-land", 10),
    ("informalityindex", 0.7),
    ("percent-prime-land", 10),
    ("initialcitylimit", 9),
    ("popgrowthrate", 3),
    ("SimulationRuntime", SIMULATION_RUNTIME),
    ("Politics", True),
    ("Develop", False),
    ("price-sensitivity", 0.1),
    ("diffusion-rate", 0.03),
    ("economicgrowthrate", 2),
    ("initialinequality", 10),
)
POLITICS_FALSE_DEVELOP_TRUE_PARAMETER_VALUES: Final[
    tuple[tuple[str, NetLogoValue], ...]
] = (
    ("staying-power", 0.3),
    ("percent-inappropriate-land", 10),
    ("informalityindex", 0.7),
    ("percent-prime-land", 10),
    ("initialcitylimit", 9),
    ("popgrowthrate", 3),
    ("SimulationRuntime", SIMULATION_RUNTIME),
    ("Politics", False),
    ("Develop", True),
    ("price-sensitivity", 0.1),
    ("diffusion-rate", 0.03),
    ("economicgrowthrate", 2),
    ("initialinequality", 10),
)
POLITICS_FALSE_DEVELOP_FALSE_PARAMETER_VALUES: Final[
    tuple[tuple[str, NetLogoValue], ...]
] = (
    ("staying-power", 0.3),
    ("percent-inappropriate-land", 10),
    ("informalityindex", 0.7),
    ("percent-prime-land", 10),
    ("initialcitylimit", 9),
    ("popgrowthrate", 3),
    ("SimulationRuntime", SIMULATION_RUNTIME),
    ("Politics", False),
    ("Develop", False),
    ("price-sensitivity", 0.1),
    ("diffusion-rate", 0.03),
    ("economicgrowthrate", 2),
    ("initialinequality", 10),
)

PRIMARY_METRIC_NAMES: Final[tuple[str, ...]] = (
    "slumpoppercent",
    "centralslumpoppercent",
    "peripheryslumpoppercent",
    "num-slums",
    "central-num-slums",
    "peripheral-num-slums",
    "slumareapercent",
    "centralslumareapercent",
    "peripheryslumareapercent",
    "slum-density",
    "central-slum-density",
    "periphery-slum-density",
)
SUPPORTING_METRIC_NAMES: Final[tuple[str, ...]] = (
    "red-density",
    "blue-density",
    "green-density",
    "smallest-slum",
)
RAW_ONLY_METRIC_NAMES: Final[tuple[str, ...]] = ("largest-slum",)
SOURCE_EMITTED_METRIC_NAMES: Final[tuple[str, ...]] = (
    PRIMARY_METRIC_NAMES + SUPPORTING_METRIC_NAMES + RAW_ONLY_METRIC_NAMES
)
PRIMARY_VALIDATION_METRICS: Final[tuple[str, ...]] = PRIMARY_METRIC_NAMES
SOURCE_EMITTED_METRICS: Final[tuple[str, ...]] = SOURCE_EMITTED_METRIC_NAMES

METRIC_CROSSWALK: Final[tuple[MetricCrosswalkEntry, ...]] = (
    MetricCrosswalkEntry(
        netlogo_name="slumpoppercent",
        mesa_alias="slum_pop_percent",
        category="primary",
        notes="Source stores slumpop divided by population, not multiplied by 100.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="centralslumpoppercent",
        mesa_alias="central_slum_pop_percent",
        category="primary",
        notes="Source stores the ward 5 slum share multiplied by 100.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="peripheryslumpoppercent",
        mesa_alias="periphery_slum_pop_percent",
        category="primary",
        notes="Source stores the peripheral slum share multiplied by 100.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="num-slums",
        mesa_alias="num_slums",
        category="primary",
        notes="Count of slum patches.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="central-num-slums",
        mesa_alias="central_num_slums",
        category="primary",
        notes="Count of slum patches in ward 5.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="peripheral-num-slums",
        mesa_alias="peripheral_num_slums",
        category="primary",
        notes="Count of slum patches outside ward 5.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="slumareapercent",
        mesa_alias="slum_area_percent",
        category="primary",
        notes="Slum patches over occupied patches, multiplied by 100.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="centralslumareapercent",
        mesa_alias="central_slum_area_percent",
        category="primary",
        notes="Central slum area over occupied central patches, multiplied by 100.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="peripheryslumareapercent",
        mesa_alias="periphery_slum_area_percent",
        category="primary",
        notes="Peripheral slum area over occupied peripheral patches.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="slum-density",
        mesa_alias="slum_density",
        category="primary",
        notes="Slum population divided by slum patch count when slums exist.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="central-slum-density",
        mesa_alias="central_slum_density",
        category="primary",
        notes="Central slum population divided by central slum patch count.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="periphery-slum-density",
        mesa_alias="periphery_slum_density",
        category="primary",
        notes="Peripheral slum population divided by peripheral slum patch count.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="red-density",
        mesa_alias="red_density",
        category="supporting",
        notes="Source-emitted class-density support metric.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="blue-density",
        mesa_alias="blue_density",
        category="supporting",
        notes="Source-emitted class-density support metric.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="green-density",
        mesa_alias="green_density",
        category="supporting",
        notes="Source-emitted class-density support metric.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="smallest-slum",
        mesa_alias="smallest_slum",
        category="supporting",
        notes="Source-emitted slum-size support metric.",
    ),
    MetricCrosswalkEntry(
        netlogo_name="largest-slum",
        mesa_alias="largest_slum",
        category="raw_only",
        notes=(
            "Retained only for raw schema compatibility; source inspection found "
            "it duplicates the smallest-slum min calculation."
        ),
    ),
)

METRIC_CROSSWALK_BY_NETLOGO_NAME: Final[dict[str, MetricCrosswalkEntry]] = {
    entry.netlogo_name: entry for entry in METRIC_CROSSWALK
}
METRIC_CROSSWALK_BY_MESA_ALIAS: Final[dict[str, MetricCrosswalkEntry]] = {
    entry.mesa_alias: entry for entry in METRIC_CROSSWALK
}

BEHAVIORSPACE_OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    ("[run number]",)
    + PARAMETER_FIELD_ORDER
    + ("[step]",)
    + SOURCE_EMITTED_METRIC_NAMES
)

TYPICAL_RUN_EXPERIMENT: Final[ExperimentSpec] = ExperimentSpec(
    name="Typical Run",
    reference_name="Typical Run 30 Rep Reference",
    setup_command=SETUP_COMMAND,
    go_command=GO_COMMAND,
    simulation_runtime=SIMULATION_RUNTIME,
    repetitions=REFERENCE_REPETITIONS,
    run_metrics_every_step=True,
    step_min=STEP_MIN,
    step_max=STEP_MAX,
    rows_per_run=ROWS_PER_RUN,
    expected_runs=30,
    expected_rows=1530,
    raw_output_columns=RAW_OUTPUT_COLUMNS,
    reference_setup_file=NETLOGO_RESULTS_DIR / "baseline_setup.xml",
    reference_raw_table=NETLOGO_RESULTS_DIR / "baseline.csv",
    parameter_combinations=(
        ParameterCombination(label="baseline", values=BASELINE_PARAMETER_VALUES),
    ),
)
POPULATION_GROWTH_RATE_EXPERIMENT: Final[ExperimentSpec] = ExperimentSpec(
    name="Population Growth Rate",
    reference_name="Population Growth Rate 30 Rep Reference",
    setup_command=SETUP_COMMAND,
    go_command=GO_COMMAND,
    simulation_runtime=SIMULATION_RUNTIME,
    repetitions=REFERENCE_REPETITIONS,
    run_metrics_every_step=True,
    step_min=STEP_MIN,
    step_max=STEP_MAX,
    rows_per_run=ROWS_PER_RUN,
    expected_runs=90,
    expected_rows=4590,
    raw_output_columns=RAW_OUTPUT_COLUMNS,
    reference_setup_file=(NETLOGO_RESULTS_DIR / "population_growth_setup.xml"),
    reference_raw_table=(NETLOGO_RESULTS_DIR / "population_growth.csv"),
    parameter_combinations=(
        ParameterCombination(
            label="popgrowthrate=2",
            values=POPGROWTHRATE_2_PARAMETER_VALUES,
        ),
        ParameterCombination(
            label="popgrowthrate=3",
            values=POPGROWTHRATE_3_PARAMETER_VALUES,
        ),
        ParameterCombination(
            label="popgrowthrate=4",
            values=POPGROWTHRATE_4_PARAMETER_VALUES,
        ),
    ),
)
POLITICS_DEVELOPMENT_ON_OFF_EXPERIMENT: Final[ExperimentSpec] = ExperimentSpec(
    name="Politics and Development ON OFF",
    reference_name="Politics and Development ON OFF 30 Rep Reference",
    setup_command=SETUP_COMMAND,
    go_command=GO_COMMAND,
    simulation_runtime=SIMULATION_RUNTIME,
    repetitions=REFERENCE_REPETITIONS,
    run_metrics_every_step=True,
    step_min=STEP_MIN,
    step_max=STEP_MAX,
    rows_per_run=ROWS_PER_RUN,
    expected_runs=120,
    expected_rows=6120,
    raw_output_columns=RAW_OUTPUT_COLUMNS,
    reference_setup_file=(NETLOGO_RESULTS_DIR / "politics_development_setup.xml"),
    reference_raw_table=(NETLOGO_RESULTS_DIR / "politics_development.csv"),
    parameter_combinations=(
        ParameterCombination(
            label="Politics=true;Develop=true",
            values=POLITICS_TRUE_DEVELOP_TRUE_PARAMETER_VALUES,
        ),
        ParameterCombination(
            label="Politics=true;Develop=false",
            values=POLITICS_TRUE_DEVELOP_FALSE_PARAMETER_VALUES,
        ),
        ParameterCombination(
            label="Politics=false;Develop=true",
            values=POLITICS_FALSE_DEVELOP_TRUE_PARAMETER_VALUES,
        ),
        ParameterCombination(
            label="Politics=false;Develop=false",
            values=POLITICS_FALSE_DEVELOP_FALSE_PARAMETER_VALUES,
        ),
    ),
)

SELECTED_EXPERIMENTS: Final[tuple[ExperimentSpec, ...]] = (
    TYPICAL_RUN_EXPERIMENT,
    POPULATION_GROWTH_RATE_EXPERIMENT,
    POLITICS_DEVELOPMENT_ON_OFF_EXPERIMENT,
)
SELECTED_EXPERIMENT_REGISTRY: Final[dict[str, ExperimentSpec]] = {
    experiment.name: experiment for experiment in SELECTED_EXPERIMENTS
}
EXPERIMENT_REGISTRY: Final[dict[str, ExperimentSpec]] = SELECTED_EXPERIMENT_REGISTRY
SELECTED_EXPERIMENT_NAMES: Final[tuple[str, ...]] = tuple(
    experiment.name for experiment in SELECTED_EXPERIMENTS
)

REFERENCE_PARAMETER_COMBINATION_COUNT: Final[int] = 8
REFERENCE_TOTAL_RUNS: Final[int] = 240
REFERENCE_TOTAL_ROWS: Final[int] = 12240
REFERENCE_SURFACE_30_REP: Final[dict[str, int | tuple[int, int]]] = {
    "parameter_combinations": REFERENCE_PARAMETER_COMBINATION_COUNT,
    "runs": REFERENCE_TOTAL_RUNS,
    "data_rows": REFERENCE_TOTAL_ROWS,
    "step_range": (STEP_MIN, STEP_MAX),
    "rows_per_run": ROWS_PER_RUN,
}

__all__ = [
    "BASELINE_PARAMETER_VALUES",
    "BEHAVIORSPACE_OUTPUT_COLUMNS",
    "CENTRAL_WARD",
    "CoordinateRange",
    "DEFAULT_MAX_SEARCH_ATTEMPTS",
    "EXECUTION_REFERENCE_NETLOGO_SOURCE",
    "EXECUTION_REFERENCE_NETLOGO_SOURCE_SHA256",
    "EXPERIMENT_REGISTRY",
    "ExperimentSpec",
    "GO_COMMAND",
    "METRIC_CROSSWALK",
    "METRIC_CROSSWALK_BY_MESA_ALIAS",
    "METRIC_CROSSWALK_BY_NETLOGO_NAME",
    "MetricCrosswalkEntry",
    "NETLOGO_RESULTS_DIR",
    "NETLOGO_SOURCE_SHA256",
    "PARAMETER_CROSSWALK",
    "PARAMETER_CROSSWALK_BY_MESA_ALIAS",
    "PARAMETER_CROSSWALK_BY_NETLOGO_NAME",
    "PARAMETER_FIELD_ORDER",
    "PERIPHERAL_WARDS",
    "POLITICS_DEVELOPMENT_ON_OFF_EXPERIMENT",
    "POPULATION_GROWTH_RATE_EXPERIMENT",
    "PRIMARY_METRIC_NAMES",
    "PRIMARY_VALIDATION_METRICS",
    "PROVENANCE_NETLOGO_SOURCE",
    "PROVENANCE_NETLOGO_SOURCE_SHA256",
    "ParameterCombination",
    "ParameterCrosswalkEntry",
    "RAW_ONLY_METRIC_NAMES",
    "RAW_OUTPUT_COLUMNS",
    "REFERENCE_PARAMETER_COMBINATION_COUNT",
    "REFERENCE_SURFACE_30_REP",
    "REFERENCE_REPETITIONS",
    "REFERENCE_TOTAL_ROWS",
    "REFERENCE_TOTAL_RUNS",
    "ROWS_PER_RUN",
    "SELECTED_EXPERIMENT_NAMES",
    "SELECTED_EXPERIMENT_REGISTRY",
    "SELECTED_EXPERIMENTS",
    "SETUP_COMMAND",
    "SIMULATION_RUNTIME",
    "SOURCE_EMITTED_METRICS",
    "SOURCE_EMITTED_METRIC_NAMES",
    "STEP_MAX",
    "STEP_MIN",
    "SUPPORTING_METRIC_NAMES",
    "TYPICAL_RUN_EXPERIMENT",
    "WARD_BOUNDS",
    "WARD_COORDINATE_RANGES",
    "WORLD_BOUNDS",
    "WORLD_HEIGHT",
    "WORLD_PATCH_COUNT",
    "WORLD_WIDTH",
    "WORLD_X_MAX",
    "WORLD_X_MIN",
    "WORLD_Y_MAX",
    "WORLD_Y_MIN",
]
