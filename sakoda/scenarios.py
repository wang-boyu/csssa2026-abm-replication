from __future__ import annotations

from dataclasses import dataclass


SQUARES = "Squares"
CROSSES = "Crosses"
GROUPS = (SQUARES, CROSSES)

DEFAULT_ROWS = 8
DEFAULT_COLUMNS = 8
DEFAULT_GROUP_SIZE = 6
DEFAULT_DISTANCE_WEIGHT = 4
DEFAULT_SEEDS = (101, 202, 303, 404, 505)
DEFAULT_STABLE_MAX_CYCLES = 50
DEFAULT_UNSTABLE_MAX_CYCLES = 100


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    name: str
    display_name: str
    source_caption: str
    squares_own: int
    squares_other: int
    crosses_own: int
    crosses_other: int
    max_cycles: int = DEFAULT_STABLE_MAX_CYCLES
    unstable_expected: bool = False
    source_pattern: str = ""
    stability_target: str = ""

    def own_valence_for(self, group: str) -> int:
        if group == SQUARES:
            return self.squares_own
        if group == CROSSES:
            return self.crosses_own
        raise ValueError(f"Unknown group: {group}")

    def other_valence_for(self, group: str) -> int:
        if group == SQUARES:
            return self.squares_other
        if group == CROSSES:
            return self.crosses_other
        raise ValueError(f"Unknown group: {group}")

    @property
    def attitude_label(self) -> str:
        return (
            f"Squares own {self.squares_own} other {self.squares_other}; "
            f"Crosses own {self.crosses_own} other {self.crosses_other}"
        )


SCENARIO_LIST = (
    ScenarioConfig(
        name="crossroads",
        display_name="Crossroads",
        source_caption="Crossroads",
        squares_own=1,
        squares_other=0,
        crosses_own=1,
        crosses_other=0,
        source_pattern=(
            "Both groups move toward the center and settle as side-by-side "
            "same-group clusters."
        ),
        stability_target="Stable in a small number of cycles; source example ends at cycle 6.",
    ),
    ScenarioConfig(
        name="mutual_suspicion",
        display_name="Mutual Suspicion",
        source_caption="Mutual Suspicion",
        squares_own=0,
        squares_other=-1,
        crosses_own=0,
        crosses_other=-1,
        source_pattern=(
            "Initially weak clusters become segregated groups; the jump option "
            "matters in the source discussion."
        ),
        stability_target="Stable segregated pattern possible; source example ends at cycle 9.",
    ),
    ScenarioConfig(
        name="segregation",
        display_name="Segregation",
        source_caption="Segregation",
        squares_own=1,
        squares_other=-1,
        crosses_own=1,
        crosses_other=-1,
        source_pattern=(
            "Cohesive in-groups separate from each other, with a source example "
            "showing withdrawal toward opposing corners."
        ),
        stability_target="Stable or strongly separated final pattern.",
    ),
    ScenarioConfig(
        name="social_climber",
        display_name="Social Climber",
        source_caption="Social Climber",
        squares_own=-1,
        squares_other=1,
        crosses_own=1,
        crosses_other=-1,
        max_cycles=DEFAULT_UNSTABLE_MAX_CYCLES,
        unstable_expected=True,
        source_pattern=(
            "Squares spread out and chase Crosses; Crosses cluster, evade, "
            "split, and may become trapped."
        ),
        stability_target="Unstable pursuit or recurrent movement expected.",
    ),
    ScenarioConfig(
        name="social_worker",
        display_name="Social Worker",
        source_caption="Social Worker",
        squares_own=1,
        squares_other=1,
        crosses_own=-1,
        crosses_other=-1,
        max_cycles=DEFAULT_UNSTABLE_MAX_CYCLES,
        unstable_expected=True,
        source_pattern=("Cohesive Squares slowly pursue scattered peripheral Crosses."),
        stability_target="Slow unstable movement expected.",
    ),
    ScenarioConfig(
        name="boy_girl",
        display_name="Boy-Girl",
        source_caption="Boy-Girl",
        squares_own=-1,
        squares_other=1,
        crosses_own=-1,
        crosses_other=1,
        source_pattern=(
            "Mixed pairs and an alternating circle develop before a stable "
            "checkerboard-like arrangement."
        ),
        stability_target="Stable alternating mixed-group checkerboard expected.",
    ),
    ScenarioConfig(
        name="couples",
        display_name="Couples",
        source_caption="Couples",
        squares_own=-4,
        squares_other=1,
        crosses_own=-4,
        crosses_other=1,
        source_pattern=(
            "Strong same-group repulsion and cross-group attraction produce "
            "dispersed mixed pairs."
        ),
        stability_target="Stable separated mixed couples expected.",
    ),
    ScenarioConfig(
        name="husband_wives",
        display_name="Husbands and Wives",
        source_caption="Husbands and Wives",
        squares_own=-4,
        squares_other=2,
        crosses_own=1,
        crosses_other=2,
        source_pattern=(
            "Crosses group centrally, several Squares surround them, and two "
            "Squares withdraw into corners."
        ),
        stability_target="Stable or source-like central Cross cluster expected.",
    ),
)

SCENARIOS = {scenario.name: scenario for scenario in SCENARIO_LIST}


def get_scenario(name: str) -> ScenarioConfig:
    try:
        return SCENARIOS[name]
    except KeyError as exc:
        available = ", ".join(SCENARIOS)
        raise ValueError(
            f"Unknown Sakoda scenario {name!r}; available: {available}"
        ) from exc
