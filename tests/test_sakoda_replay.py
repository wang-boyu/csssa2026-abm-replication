from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path

import sakoda
from sakoda import app, replay
from sakoda.replay import (
    ALL_SCENARIO_TERMINAL_SPECS,
    CROSSROADS_TRAJECTORY_CYCLES,
    PUBLICATION_SEED,
    replay_all_scenario_terminals,
    replay_crossroads_trajectory,
)
from sakoda.scenarios import SCENARIO_LIST

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RETAINED_RUNS_DIR = REPOSITORY_ROOT / "results" / "sakoda" / "runs"


def _position_set(
    records: list[dict[str, object]],
) -> frozenset[tuple[str, int, int, int]]:
    return frozenset(
        (
            str(record["group"]),
            int(record["piece_number"]),
            int(record["row"]),
            int(record["column"]),
        )
        for record in records
    )


def _snapshot_position_set(
    snapshot: replay.PublicationBoardSnapshot,
) -> frozenset[tuple[str, int, int, int]]:
    return frozenset(
        (piece.group, piece.piece_number, piece.row, piece.column)
        for piece in snapshot.pieces
    )


def _retained_run(scenario_name: str) -> dict[str, object]:
    path = RETAINED_RUNS_DIR / f"{scenario_name}_seed_{PUBLICATION_SEED}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"Retained run must be a JSON object: {path}")
    return payload


def _positions_for_cycle(
    payload: dict[str, object], cycle: int
) -> frozenset[tuple[str, int, int, int]]:
    positions_by_cycle = payload["positions_by_cycle"]
    if not isinstance(positions_by_cycle, list):
        raise AssertionError("positions_by_cycle must be a list")
    matching = [
        item
        for item in positions_by_cycle
        if isinstance(item, dict) and item.get("cycle") == cycle
    ]
    if len(matching) != 1 or not isinstance(matching[0].get("positions"), list):
        raise AssertionError(f"Expected one retained snapshot for cycle {cycle}")
    return _position_set(matching[0]["positions"])


class SakodaReplayTests(unittest.TestCase):
    def test_package_app_and_replay_modules_import(self) -> None:
        self.assertIs(importlib.import_module("sakoda"), sakoda)
        self.assertIs(importlib.import_module("sakoda.app"), app)
        self.assertIs(importlib.import_module("sakoda.replay"), replay)

    def test_crossroads_trajectory_matches_retained_cycle_snapshots(self) -> None:
        retained = _retained_run("crossroads")
        snapshots = replay_crossroads_trajectory()

        self.assertEqual(
            tuple(snapshot.cycle for snapshot in snapshots),
            CROSSROADS_TRAJECTORY_CYCLES,
        )
        for snapshot in snapshots:
            with self.subTest(cycle=snapshot.cycle):
                self.assertEqual(snapshot.scenario_name, "crossroads")
                self.assertEqual(snapshot.seed, PUBLICATION_SEED)
                self.assertEqual(
                    _snapshot_position_set(snapshot),
                    _positions_for_cycle(retained, snapshot.cycle),
                )

        self.assertEqual(snapshots, replay_crossroads_trajectory())

    def test_all_terminal_replays_match_retained_final_positions(self) -> None:
        snapshots = replay_all_scenario_terminals()

        self.assertEqual(len(snapshots), 8)
        self.assertEqual(
            tuple(snapshot.scenario_name for snapshot in snapshots),
            tuple(scenario.name for scenario in SCENARIO_LIST),
        )
        self.assertEqual(
            tuple(spec.name for spec in ALL_SCENARIO_TERMINAL_SPECS),
            tuple(scenario.name for scenario in SCENARIO_LIST),
        )

        for snapshot in snapshots:
            retained = _retained_run(snapshot.scenario_name)
            final_positions = retained["final_positions"]
            if not isinstance(final_positions, list):
                raise AssertionError("final_positions must be a list")
            with self.subTest(scenario=snapshot.scenario_name):
                self.assertEqual(snapshot.seed, PUBLICATION_SEED)
                self.assertEqual(snapshot.cycle, retained["cycles_completed"])
                self.assertEqual(snapshot.model_stop_reason, retained["stop_reason"])
                self.assertEqual(
                    _snapshot_position_set(snapshot),
                    _position_set(final_positions),
                )

        self.assertEqual(snapshots, replay_all_scenario_terminals())

    def test_publication_renderer_module_is_not_part_of_package(self) -> None:
        module_path = Path(sakoda.__file__).resolve().parent
        self.assertFalse((module_path / "publication_visuals.py").exists())


if __name__ == "__main__":
    unittest.main()
