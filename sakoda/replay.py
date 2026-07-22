"""Deterministic in-memory snapshots used by the Sakoda application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sakoda.model import (
    JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
    MOVEMENT_ORDER_ALL_RANDOM,
    SakodaModel,
)
from sakoda.scenarios import SQUARES

PUBLICATION_SEED: Final = 101
PUBLICATION_JUMP_RULE: Final = JUMP_RULE_NO_ADJACENT_IMPROVEMENT
PUBLICATION_MOVEMENT_ORDER: Final = MOVEMENT_ORDER_ALL_RANDOM
CROSSROADS_TRAJECTORY_CYCLES: Final = (0, 3, 5)
STABLE_MODEL_STOP_REASON: Final = "stable_no_position_changes"


@dataclass(frozen=True, slots=True)
class PublicationScenarioSpec:
    """Expected terminal display metadata for one seed-101 scenario."""

    name: str
    display_name: str
    cycle: int
    stop_state: str
    validation_status: str
    model_stop_reason: str


ALL_SCENARIO_TERMINAL_SPECS: Final = (
    PublicationScenarioSpec(
        "crossroads",
        "Crossroads",
        5,
        "stable",
        "directionally matched",
        STABLE_MODEL_STOP_REASON,
    ),
    PublicationScenarioSpec(
        "mutual_suspicion",
        "Mutual Suspicion",
        13,
        "stable",
        "directionally matched",
        STABLE_MODEL_STOP_REASON,
    ),
    PublicationScenarioSpec(
        "segregation",
        "Segregation",
        9,
        "stable",
        "directionally matched",
        STABLE_MODEL_STOP_REASON,
    ),
    PublicationScenarioSpec(
        "social_climber",
        "Social Climber",
        100,
        "persistent/recurrent movement",
        "directionally matched",
        "persistent_or_recurrent_movement_max_cycles",
    ),
    PublicationScenarioSpec(
        "social_worker",
        "Social Worker",
        11,
        "stable",
        "unresolved",
        STABLE_MODEL_STOP_REASON,
    ),
    PublicationScenarioSpec(
        "boy_girl",
        "Boy-Girl",
        3,
        "stable",
        "unresolved",
        STABLE_MODEL_STOP_REASON,
    ),
    PublicationScenarioSpec(
        "couples",
        "Couples",
        8,
        "stable",
        "directionally matched",
        STABLE_MODEL_STOP_REASON,
    ),
    PublicationScenarioSpec(
        "husband_wives",
        "Husbands and Wives",
        5,
        "stable",
        "directionally matched",
        STABLE_MODEL_STOP_REASON,
    ),
)


@dataclass(frozen=True, slots=True)
class PublicationPieceSnapshot:
    group: str
    piece_number: int
    row: int
    column: int
    label: str


@dataclass(frozen=True, slots=True)
class PublicationBoardSnapshot:
    scenario_name: str
    scenario_label: str
    seed: int
    cycle: int
    rows: int
    columns: int
    running: bool
    model_stop_reason: str
    stop_state: str
    pieces: tuple[PublicationPieceSnapshot, ...]
    jump_rule: str = PUBLICATION_JUMP_RULE
    movement_order: str = PUBLICATION_MOVEMENT_ORDER


def display_stop_state(model_stop_reason: str) -> str:
    """Return the neutral display label for an internal model stop reason."""

    if model_stop_reason == STABLE_MODEL_STOP_REASON:
        return "stable"
    if model_stop_reason == "persistent_or_recurrent_movement_max_cycles":
        return "persistent/recurrent movement"
    return model_stop_reason


def terminal_spec_for_scenario(scenario_name: str) -> PublicationScenarioSpec:
    for spec in ALL_SCENARIO_TERMINAL_SPECS:
        if spec.name == scenario_name:
            return spec
    available = ", ".join(spec.name for spec in ALL_SCENARIO_TERMINAL_SPECS)
    raise ValueError(f"Unknown scenario {scenario_name!r}; available: {available}")


def replay_scenario_snapshot(
    scenario_name: str,
    cycle: int,
) -> PublicationBoardSnapshot:
    """Replay a fresh model and freeze one cycle for application display."""

    if isinstance(cycle, bool) or cycle < 0:
        raise ValueError("Replay cycle must be a non-negative integer.")

    model = _create_replay_model(scenario_name)
    while model.running and model.cycle < cycle:
        model.step()
    if model.cycle != cycle:
        raise ValueError(
            f"Scenario {scenario_name!r} stopped at cycle {model.cycle}; "
            f"cannot return requested cycle {cycle}."
        )
    return _snapshot_from_model(model)


def replay_crossroads_trajectory() -> tuple[PublicationBoardSnapshot, ...]:
    """Return the fixed Crossroads cycle 0, 3, and 5 snapshots."""

    snapshots = tuple(
        replay_scenario_snapshot("crossroads", cycle)
        for cycle in CROSSROADS_TRAJECTORY_CYCLES
    )
    terminal_spec = terminal_spec_for_scenario("crossroads")
    _assert_terminal_contract(snapshots[-1], terminal_spec)
    return snapshots


def replay_all_scenario_terminals() -> tuple[PublicationBoardSnapshot, ...]:
    """Return all eight settled or max-cycle snapshots in display order."""

    snapshots: list[PublicationBoardSnapshot] = []
    for spec in ALL_SCENARIO_TERMINAL_SPECS:
        model = _create_replay_model(spec.name)
        model.run()
        snapshot = _snapshot_from_model(model)
        _assert_terminal_contract(snapshot, spec)
        snapshots.append(snapshot)
    return tuple(snapshots)


def _create_replay_model(scenario_name: str) -> SakodaModel:
    return SakodaModel(
        scenario_name,
        seed=PUBLICATION_SEED,
        jump_rule=PUBLICATION_JUMP_RULE,
        movement_order=PUBLICATION_MOVEMENT_ORDER,
    )


def _snapshot_from_model(model: SakodaModel) -> PublicationBoardSnapshot:
    pieces = tuple(
        PublicationPieceSnapshot(
            group=str(position["group"]),
            piece_number=int(position["piece_number"]),
            row=int(position["row"]),
            column=int(position["column"]),
            label=(
                f"S{position['piece_number']}"
                if position["group"] == SQUARES
                else f"X{position['piece_number']}"
            ),
        )
        for position in model.positions_snapshot()
    )
    return PublicationBoardSnapshot(
        scenario_name=model.scenario.name,
        scenario_label=model.scenario.display_name,
        seed=int(model.seed_value),
        cycle=model.cycle,
        rows=model.rows,
        columns=model.columns,
        running=model.running,
        model_stop_reason=model.stop_reason,
        stop_state=display_stop_state(model.stop_reason),
        pieces=pieces,
        jump_rule=model.jump_rule,
        movement_order=model.movement_order,
    )


def _assert_terminal_contract(
    snapshot: PublicationBoardSnapshot,
    spec: PublicationScenarioSpec,
) -> None:
    actual = (
        snapshot.scenario_name,
        snapshot.scenario_label,
        snapshot.cycle,
        snapshot.stop_state,
        snapshot.model_stop_reason,
        snapshot.running,
        snapshot.jump_rule,
        snapshot.movement_order,
    )
    expected = (
        spec.name,
        spec.display_name,
        spec.cycle,
        spec.stop_state,
        spec.model_stop_reason,
        False,
        PUBLICATION_JUMP_RULE,
        PUBLICATION_MOVEMENT_ORDER,
    )
    if actual != expected:
        raise RuntimeError(
            f"Replay for {spec.name!r} differs from its terminal contract: "
            f"expected {expected!r}, got {actual!r}."
        )


__all__ = [
    "ALL_SCENARIO_TERMINAL_SPECS",
    "CROSSROADS_TRAJECTORY_CYCLES",
    "PUBLICATION_JUMP_RULE",
    "PUBLICATION_MOVEMENT_ORDER",
    "PUBLICATION_SEED",
    "STABLE_MODEL_STOP_REASON",
    "PublicationBoardSnapshot",
    "PublicationPieceSnapshot",
    "PublicationScenarioSpec",
    "display_stop_state",
    "replay_all_scenario_terminals",
    "replay_crossroads_trajectory",
    "replay_scenario_snapshot",
    "terminal_spec_for_scenario",
]
