from __future__ import annotations

import math
import unittest
from collections.abc import Sequence

from sakoda.model import (
    JUMP_RULE_ENDPOINT_ONLY,
    JUMP_RULE_NO_ADJACENT_AVAILABLE,
    JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
    MOVEMENT_ORDER_ALL_RANDOM,
    MOVEMENT_ORDER_GROUPS_SEQUENTIAL,
    MoveDecision,
    SakodaModel,
    SakodaPiece,
)
from sakoda.scenarios import (
    CROSSES,
    SCENARIOS,
    SCENARIO_LIST,
    SQUARES,
    ScenarioConfig,
    get_scenario,
)


def scenario_config(**overrides: object) -> ScenarioConfig:
    values = {
        "name": "test_scenario",
        "display_name": "Test Scenario",
        "source_caption": "Test Scenario",
        "squares_own": 0,
        "squares_other": 0,
        "crosses_own": 0,
        "crosses_other": 0,
    }
    values.update(overrides)
    return ScenarioConfig(**values)


def initial_positions(
    *,
    squares: Sequence[tuple[int, int]],
    crosses: Sequence[tuple[int, int]],
) -> dict[tuple[str, int], tuple[int, int]]:
    if len(squares) != len(crosses):
        raise ValueError("Sakoda tests use equal group sizes.")
    positions: dict[tuple[str, int], tuple[int, int]] = {}
    for piece_number, position in enumerate(squares, start=1):
        positions[(SQUARES, piece_number)] = position
    for piece_number, position in enumerate(crosses, start=1):
        positions[(CROSSES, piece_number)] = position
    return positions


def piece_for(model: SakodaModel, group: str, piece_number: int) -> SakodaPiece:
    for piece in model.pieces:
        if piece.group == group and piece.piece_number == piece_number:
            return piece
    raise AssertionError(f"Missing piece {group} {piece_number}.")


class SakodaScenarioTests(unittest.TestCase):
    def test_all_eight_source_scenarios_define_expected_attitude_matrices(self) -> None:
        expected = {
            "crossroads": (1, 0, 1, 0),
            "mutual_suspicion": (0, -1, 0, -1),
            "segregation": (1, -1, 1, -1),
            "social_climber": (-1, 1, 1, -1),
            "social_worker": (1, 1, -1, -1),
            "boy_girl": (-1, 1, -1, 1),
            "couples": (-4, 1, -4, 1),
            "husband_wives": (-4, 2, 1, 2),
        }

        self.assertEqual([scenario.name for scenario in SCENARIO_LIST], list(expected))
        self.assertEqual(set(SCENARIOS), set(expected))

        for name, matrix in expected.items():
            scenario = get_scenario(name)
            self.assertEqual(
                (
                    scenario.squares_own,
                    scenario.squares_other,
                    scenario.crosses_own,
                    scenario.crosses_other,
                ),
                matrix,
            )
            self.assertEqual(scenario.own_valence_for(SQUARES), matrix[0])
            self.assertEqual(scenario.other_valence_for(SQUARES), matrix[1])
            self.assertEqual(scenario.own_valence_for(CROSSES), matrix[2])
            self.assertEqual(scenario.other_valence_for(CROSSES), matrix[3])


class SakodaModelMechanicsTests(unittest.TestCase):
    def test_score_position_uses_squared_distance_and_distance_weight_formula(
        self,
    ) -> None:
        scenario = scenario_config(squares_own=2, squares_other=-1)
        model = SakodaModel(
            scenario,
            seed=7,
            rows=5,
            columns=5,
            group_size=2,
            distance_weight=4,
            max_cycles=1,
            initial_positions=initial_positions(
                squares=[(2, 2), (2, 1)],
                crosses=[(5, 3), (1, 5)],
            ),
        )
        piece = piece_for(model, SQUARES, 1)

        score = model.score_position(piece, row=2, column=3)

        expected = 2 / (4 ** (1 / 4)) - 1 / (9 ** (1 / 4)) - 1 / (5 ** (1 / 4))
        self.assertAlmostEqual(score, expected)

    def test_available_positions_within_radius_one_lists_adjacent_legal_moves(
        self,
    ) -> None:
        model = SakodaModel(
            scenario_config(),
            seed=1,
            rows=4,
            columns=4,
            group_size=2,
            max_cycles=1,
            initial_positions=initial_positions(
                squares=[(2, 2), (1, 1)],
                crosses=[(2, 3), (4, 4)],
            ),
        )

        self.assertEqual(
            model.available_positions_within((2, 2), radius=1),
            [(1, 2), (1, 3), (2, 1), (3, 1), (3, 2), (3, 3)],
        )

    def test_distance_two_search_triggers_after_no_adjacent_improvement(self) -> None:
        model = SakodaModel(
            scenario_config(),
            seed=3,
            rows=5,
            columns=5,
            group_size=2,
            max_cycles=1,
            initial_positions=initial_positions(
                squares=[(3, 3), (5, 5)],
                crosses=[(5, 4), (4, 5)],
            ),
        )
        piece = piece_for(model, SQUARES, 1)
        adjacent_candidates = model.available_positions_within(piece.position, radius=1)
        distance_two_candidates = model.available_positions_within(
            piece.position,
            radius=2,
        )
        scored_positions: list[tuple[int, int]] = []

        def fake_score(scored_piece: SakodaPiece, row: int, column: int) -> float:
            self.assertIs(scored_piece, piece)
            scored_positions.append((row, column))
            if (row, column) == piece.position:
                return 0.0
            if max(abs(row - piece.row), abs(column - piece.column)) <= 1:
                return 0.0
            if (row, column) == (1, 1):
                return 1.0
            return 0.0

        model.score_position = fake_score  # type: ignore[method-assign]

        decision = model.choose_move(piece)

        occupied = {(3, 3), (5, 5), (5, 4), (4, 5)}
        expected_chebyshev_radius_two = {
            (row, column)
            for row in range(1, 6)
            for column in range(1, 6)
            if (row, column) not in occupied and max(abs(row - 3), abs(column - 3)) <= 2
        }
        self.assertEqual(set(distance_two_candidates), expected_chebyshev_radius_two)
        self.assertIn((2, 2), distance_two_candidates)
        self.assertIn((1, 1), distance_two_candidates)
        self.assertEqual(decision.destination, (1, 1))
        self.assertEqual(decision.search_radius, 2)
        self.assertEqual(decision.candidate_count, len(distance_two_candidates))
        self.assertTrue(decision.moved)
        self.assertEqual(scored_positions[0], piece.position)
        self.assertEqual(
            scored_positions[1 : 1 + len(adjacent_candidates)],
            adjacent_candidates,
        )
        self.assertEqual(
            scored_positions[1 + len(adjacent_candidates) :],
            distance_two_candidates,
        )

    def test_default_options_preserve_original_jump_and_movement_conventions(
        self,
    ) -> None:
        model = SakodaModel(
            scenario_config(),
            seed=31,
            rows=5,
            columns=5,
            group_size=2,
            max_cycles=1,
            initial_positions=initial_positions(
                squares=[(3, 3), (5, 5)],
                crosses=[(5, 4), (4, 5)],
            ),
        )

        self.assertEqual(model.jump_rule, JUMP_RULE_NO_ADJACENT_IMPROVEMENT)
        self.assertEqual(model.movement_order, MOVEMENT_ORDER_ALL_RANDOM)

        run_record = model.to_run_record()
        self.assertEqual(run_record["jump_rule"], JUMP_RULE_NO_ADJACENT_IMPROVEMENT)
        self.assertIn(
            "when_no_adjacent_strict_improvement",
            run_record["jump_rule_description"],
        )
        self.assertEqual(run_record["movement_order"], MOVEMENT_ORDER_ALL_RANDOM)
        self.assertEqual(
            run_record["movement_order_description"],
            "one_seeded_random_shuffle_of_all_pieces_per_cycle",
        )

    def test_no_adjacent_available_jump_rule_skips_radius_two_when_adjacent_open(
        self,
    ) -> None:
        model = SakodaModel(
            scenario_config(),
            seed=32,
            rows=5,
            columns=5,
            group_size=2,
            max_cycles=1,
            jump_rule=JUMP_RULE_NO_ADJACENT_AVAILABLE,
            initial_positions=initial_positions(
                squares=[(3, 3), (5, 5)],
                crosses=[(5, 4), (4, 5)],
            ),
        )
        piece = piece_for(model, SQUARES, 1)
        adjacent_candidates = model.available_positions_within(piece.position, radius=1)
        scored_positions: list[tuple[int, int]] = []

        def fake_score(scored_piece: SakodaPiece, row: int, column: int) -> float:
            self.assertIs(scored_piece, piece)
            scored_positions.append((row, column))
            if (row, column) == (1, 1):
                return 1.0
            return 0.0

        model.score_position = fake_score  # type: ignore[method-assign]

        decision = model.choose_move(piece)

        self.assertTrue(adjacent_candidates)
        self.assertFalse(decision.moved)
        self.assertEqual(decision.destination, piece.position)
        self.assertEqual(decision.search_radius, 0)
        self.assertEqual(decision.candidate_count, len(adjacent_candidates))
        self.assertNotIn((1, 1), scored_positions)
        self.assertEqual(scored_positions[1:], adjacent_candidates)

    def test_no_adjacent_available_jump_rule_uses_radius_two_when_immobile(
        self,
    ) -> None:
        model = SakodaModel(
            scenario_config(),
            seed=33,
            rows=5,
            columns=5,
            group_size=5,
            max_cycles=1,
            jump_rule=JUMP_RULE_NO_ADJACENT_AVAILABLE,
            initial_positions=initial_positions(
                squares=[(3, 3), (2, 2), (2, 3), (2, 4), (3, 2)],
                crosses=[(3, 4), (4, 2), (4, 3), (4, 4), (5, 5)],
            ),
        )
        piece = piece_for(model, SQUARES, 1)
        adjacent_candidates = model.available_positions_within(piece.position, radius=1)
        distance_two_candidates = model.available_positions_within(
            piece.position,
            radius=2,
        )

        def fake_score(scored_piece: SakodaPiece, row: int, column: int) -> float:
            self.assertIs(scored_piece, piece)
            if (row, column) == piece.position:
                return 0.0
            if (row, column) == (1, 1):
                return 1.0
            return 0.0

        model.score_position = fake_score  # type: ignore[method-assign]

        decision = model.choose_move(piece)

        self.assertEqual(adjacent_candidates, [])
        self.assertIn((1, 1), distance_two_candidates)
        self.assertTrue(decision.moved)
        self.assertEqual(decision.destination, (1, 1))
        self.assertEqual(decision.search_radius, 2)
        self.assertEqual(decision.candidate_count, len(distance_two_candidates))

    def test_endpoint_only_jump_rule_excludes_non_endpoint_radius_two_cells(
        self,
    ) -> None:
        model = SakodaModel(
            scenario_config(),
            seed=34,
            rows=5,
            columns=5,
            group_size=2,
            max_cycles=1,
            jump_rule=JUMP_RULE_ENDPOINT_ONLY,
            initial_positions=initial_positions(
                squares=[(3, 3), (5, 5)],
                crosses=[(5, 4), (4, 5)],
            ),
        )
        piece = piece_for(model, SQUARES, 1)
        all_radius_two = model.available_positions_within(piece.position, radius=2)
        endpoint_candidates = model.available_distance_two_endpoints(piece.position)

        def fake_score(scored_piece: SakodaPiece, row: int, column: int) -> float:
            self.assertIs(scored_piece, piece)
            if (row, column) == piece.position:
                return 0.0
            if (row, column) == (1, 2):
                return 2.0
            if (row, column) == (1, 1):
                return 1.0
            return 0.0

        model.score_position = fake_score  # type: ignore[method-assign]

        decision = model.choose_move(piece)

        self.assertIn((1, 2), all_radius_two)
        self.assertNotIn((1, 2), endpoint_candidates)
        self.assertIn((1, 1), endpoint_candidates)
        self.assertLess(len(endpoint_candidates), len(all_radius_two))
        self.assertEqual(decision.destination, (1, 1))
        self.assertEqual(decision.search_radius, 2)
        self.assertEqual(decision.candidate_count, len(endpoint_candidates))

    def test_group_sequential_movement_order_is_observable_in_cycle_order(
        self,
    ) -> None:
        positions = initial_positions(
            squares=[(1, 1), (1, 2), (1, 3)],
            crosses=[(4, 1), (4, 2), (4, 3)],
        )

        def observed_order(movement_order: str) -> list[tuple[str, int]]:
            model = SakodaModel(
                scenario_config(),
                seed=1,
                rows=4,
                columns=4,
                group_size=3,
                max_cycles=1,
                movement_order=movement_order,
                initial_positions=positions,
            )
            observed: list[tuple[str, int]] = []

            def fake_choose_move(piece: SakodaPiece) -> MoveDecision:
                observed.append((piece.group, piece.piece_number))
                return MoveDecision(
                    destination=piece.position,
                    stay_score=0.0,
                    selected_score=0.0,
                    search_radius=0,
                    candidate_count=0,
                    moved=False,
                )

            model.choose_move = fake_choose_move  # type: ignore[method-assign]
            model.step()
            return observed

        all_random_order = observed_order(MOVEMENT_ORDER_ALL_RANDOM)
        group_sequential_order = observed_order(MOVEMENT_ORDER_GROUPS_SEQUENTIAL)

        self.assertNotEqual(group_sequential_order, all_random_order)
        self.assertEqual(
            [group for group, _ in group_sequential_order],
            [SQUARES, SQUARES, SQUARES, CROSSES, CROSSES, CROSSES],
        )
        self.assertCountEqual(
            group_sequential_order,
            [
                (SQUARES, 1),
                (SQUARES, 2),
                (SQUARES, 3),
                (CROSSES, 1),
                (CROSSES, 2),
                (CROSSES, 3),
            ],
        )

    def test_invalid_sensitivity_option_names_fail_clearly(self) -> None:
        common_kwargs = {
            "seed": 35,
            "rows": 4,
            "columns": 4,
            "group_size": 2,
            "max_cycles": 1,
            "initial_positions": initial_positions(
                squares=[(2, 2), (1, 1)],
                crosses=[(4, 4), (1, 4)],
            ),
        }

        with self.assertRaisesRegex(ValueError, "Unknown jump_rule.*bogus"):
            SakodaModel(
                scenario_config(),
                jump_rule="bogus",
                **common_kwargs,
            )
        with self.assertRaisesRegex(ValueError, "Unknown movement_order.*bogus"):
            SakodaModel(
                scenario_config(),
                movement_order="bogus",
                **common_kwargs,
            )

    def test_equal_score_moves_prefer_staying(self) -> None:
        model = SakodaModel(
            scenario_config(),
            seed=4,
            rows=4,
            columns=4,
            group_size=2,
            max_cycles=1,
            initial_positions=initial_positions(
                squares=[(2, 2), (1, 1)],
                crosses=[(4, 4), (1, 4)],
            ),
        )
        piece = piece_for(model, SQUARES, 1)

        decision = model.choose_move(piece)

        self.assertFalse(decision.moved)
        self.assertEqual(decision.destination, piece.position)
        self.assertEqual(decision.search_radius, 0)
        self.assertEqual(decision.selected_score, decision.stay_score)

    def test_equal_moving_score_ties_are_seeded_random_choices(self) -> None:
        def tied_destination(seed: int) -> tuple[int, int]:
            model = SakodaModel(
                scenario_config(),
                seed=seed,
                rows=4,
                columns=4,
                group_size=2,
                max_cycles=1,
                initial_positions=initial_positions(
                    squares=[(2, 2), (4, 4)],
                    crosses=[(1, 4), (4, 1)],
                ),
            )
            piece = piece_for(model, SQUARES, 1)

            def fake_score(
                scored_piece: SakodaPiece,
                row: int,
                column: int,
            ) -> float:
                self.assertIs(scored_piece, piece)
                if (row, column) == piece.position:
                    return 0.0
                return 1.0

            model.score_position = fake_score  # type: ignore[method-assign]
            decision = model.choose_move(piece)
            self.assertEqual(decision.search_radius, 1)
            self.assertTrue(decision.moved)
            return decision.destination

        repeated_seed_destinations = [tied_destination(17) for _ in range(3)]
        self.assertEqual(
            repeated_seed_destinations,
            [repeated_seed_destinations[0]] * len(repeated_seed_destinations),
        )
        self.assertGreater(
            len({tied_destination(seed) for seed in range(1, 10)}),
            1,
        )

    def test_full_cycle_with_no_position_changes_stops_as_stable(self) -> None:
        model = SakodaModel(
            scenario_config(max_cycles=5),
            seed=5,
            rows=4,
            columns=4,
            group_size=2,
            initial_positions=initial_positions(
                squares=[(2, 2), (1, 1)],
                crosses=[(4, 4), (1, 4)],
            ),
        )
        initial_snapshot = model.positions_snapshot()

        model.step()

        self.assertFalse(model.running)
        self.assertEqual(model.stop_reason, "stable_no_position_changes")
        self.assertEqual(model.cycle, 1)
        self.assertEqual(model.positions_snapshot(), initial_snapshot)
        self.assertTrue(model.metrics_by_cycle[-1]["stable"])
        self.assertEqual(model.metrics_by_cycle[-1]["movement_count"], 0)

    def test_no_position_change_stability_also_stops_unstable_expected_scenarios(
        self,
    ) -> None:
        model = SakodaModel(
            scenario_config(max_cycles=5, unstable_expected=True),
            seed=5,
            rows=4,
            columns=4,
            group_size=2,
            initial_positions=initial_positions(
                squares=[(2, 2), (1, 1)],
                crosses=[(4, 4), (1, 4)],
            ),
        )

        model.step()

        self.assertFalse(model.running)
        self.assertEqual(model.stop_reason, "stable_no_position_changes")
        self.assertEqual(model.cycle, 1)
        self.assertTrue(model.metrics_by_cycle[-1]["stable"])
        self.assertEqual(model.metrics_by_cycle[-1]["movement_count"], 0)

    def test_initial_metrics_include_centroids_distance_and_dispersion(self) -> None:
        model = SakodaModel(
            scenario_config(),
            seed=6,
            rows=4,
            columns=4,
            group_size=2,
            max_cycles=1,
            initial_positions=initial_positions(
                squares=[(1, 1), (1, 3)],
                crosses=[(4, 4), (4, 2)],
            ),
        )

        metrics = model.metrics_by_cycle[0]

        self.assertEqual(metrics["squares_centroid_row"], 1.0)
        self.assertEqual(metrics["squares_centroid_column"], 2.0)
        self.assertEqual(metrics["crosses_centroid_row"], 4.0)
        self.assertEqual(metrics["crosses_centroid_column"], 3.0)
        self.assertAlmostEqual(metrics["centroid_distance"], math.sqrt(10))
        self.assertAlmostEqual(metrics["squares_dispersion"], 1.0)
        self.assertAlmostEqual(metrics["crosses_dispersion"], 1.0)


if __name__ == "__main__":
    unittest.main()
