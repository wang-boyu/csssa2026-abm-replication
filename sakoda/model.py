from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from mesa import Agent, Model

from .scenarios import (
    CROSSES,
    DEFAULT_COLUMNS,
    DEFAULT_DISTANCE_WEIGHT,
    DEFAULT_GROUP_SIZE,
    DEFAULT_ROWS,
    GROUPS,
    SQUARES,
    ScenarioConfig,
    get_scenario,
)


Coordinate = tuple[int, int]
InitialPositionMap = dict[tuple[str, int], Coordinate]
FLOAT_TOLERANCE = 1e-12
JUMP_RULE_NO_ADJACENT_IMPROVEMENT = "no_adjacent_improvement"
JUMP_RULE_NO_ADJACENT_AVAILABLE = "no_adjacent_available"
JUMP_RULE_ENDPOINT_ONLY = "endpoint_only"
JUMP_RULES = (
    JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
    JUMP_RULE_NO_ADJACENT_AVAILABLE,
    JUMP_RULE_ENDPOINT_ONLY,
)
MOVEMENT_ORDER_ALL_RANDOM = "all_random"
MOVEMENT_ORDER_GROUPS_SEQUENTIAL = "groups_sequential"
MOVEMENT_ORDERS = (
    MOVEMENT_ORDER_ALL_RANDOM,
    MOVEMENT_ORDER_GROUPS_SEQUENTIAL,
)


@dataclass(frozen=True, slots=True)
class MoveDecision:
    destination: Coordinate
    stay_score: float
    selected_score: float
    search_radius: int
    candidate_count: int
    moved: bool


class SakodaPiece(Agent):
    def __init__(
        self,
        model: SakodaModel,
        *,
        group: str,
        piece_number: int,
        row: int,
        column: int,
        own_group_valence: int,
        other_group_valence: int,
    ) -> None:
        super().__init__(model)
        self.group = group
        self.piece_number = piece_number
        self.row = row
        self.column = column
        self.own_group_valence = own_group_valence
        self.other_group_valence = other_group_valence

    @property
    def position(self) -> Coordinate:
        return (self.row, self.column)

    @property
    def symbol(self) -> str:
        prefix = "S" if self.group == SQUARES else "X"
        return f"{prefix}{self.piece_number}"

    def valence_toward(self, other: SakodaPiece) -> int:
        if other.group == self.group:
            return self.own_group_valence
        return self.other_group_valence

    def as_record(self) -> dict[str, int | str]:
        return {
            "group": self.group,
            "piece_number": self.piece_number,
            "row": self.row,
            "column": self.column,
            "own_group_valence": self.own_group_valence,
            "other_group_valence": self.other_group_valence,
        }


class SakodaModel(Model):
    """Source-faithful qualitative Sakoda checkerboard replication.

    The model keeps Sakoda row/column coordinates directly: rows are 1..N
    top-to-bottom and columns are 1..N left-to-right. Scoring treats columns
    as X and rows as Y, which preserves the paper's squared-distance formula.
    """

    def __init__(
        self,
        scenario: ScenarioConfig | str,
        *,
        seed: int | None = None,
        rows: int = DEFAULT_ROWS,
        columns: int = DEFAULT_COLUMNS,
        group_size: int = DEFAULT_GROUP_SIZE,
        distance_weight: int = DEFAULT_DISTANCE_WEIGHT,
        max_cycles: int | None = None,
        initial_positions: InitialPositionMap | None = None,
        jump_rule: str = JUMP_RULE_NO_ADJACENT_IMPROVEMENT,
        movement_order: str = MOVEMENT_ORDER_ALL_RANDOM,
    ) -> None:
        super().__init__(seed=seed)
        if isinstance(scenario, str):
            scenario = get_scenario(scenario)

        if rows < 2 or columns < 2:
            raise ValueError("Sakoda board must have at least 2 rows and 2 columns.")
        if group_size < 1:
            raise ValueError("group_size must be positive.")
        if group_size * len(GROUPS) > rows * columns:
            raise ValueError("The board cannot hold all requested pieces.")
        if distance_weight <= 0:
            raise ValueError("distance_weight must be positive.")
        if jump_rule not in JUMP_RULES:
            raise ValueError(
                f"Unknown jump_rule {jump_rule!r}; available: {', '.join(JUMP_RULES)}"
            )
        if movement_order not in MOVEMENT_ORDERS:
            raise ValueError(
                f"Unknown movement_order {movement_order!r}; "
                f"available: {', '.join(MOVEMENT_ORDERS)}"
            )

        self.scenario = scenario
        self.seed_value = seed
        self.rows = rows
        self.columns = columns
        self.group_size = group_size
        self.distance_weight = distance_weight
        self.max_cycles = scenario.max_cycles if max_cycles is None else max_cycles
        self.jump_rule = jump_rule
        self.movement_order = movement_order
        self.cycle = 0
        self.running = True
        self.stop_reason = "running"

        self.pieces: list[SakodaPiece] = []
        self._occupancy: dict[Coordinate, SakodaPiece] = {}
        self.metrics_by_cycle: list[dict[str, Any]] = []
        self.positions_by_cycle: list[dict[str, Any]] = []

        self._create_pieces(initial_positions=initial_positions)
        self._record_cycle_state(movement_count=0, movement_by_group={}, stable=False)

    def run(self) -> SakodaModel:
        while self.running:
            self.step()
        return self

    def step(self) -> None:
        if not self.running:
            return
        if self.cycle >= self.max_cycles:
            self.running = False
            self.stop_reason = self._max_cycle_stop_reason()
            return

        movement_order = self._movement_order_for_cycle()

        movement_count = 0
        movement_by_group = {group: 0 for group in GROUPS}

        for piece in movement_order:
            origin = piece.position
            decision = self.choose_move(piece)
            if decision.moved:
                self._move_piece(piece, decision.destination)
                movement_count += 1
                movement_by_group[piece.group] += 1
            else:
                # Staying on equal score is part of the aligned convention.
                assert piece.position == origin

        self.cycle += 1
        stable = movement_count == 0
        if stable:
            self.running = False
            self.stop_reason = "stable_no_position_changes"
        elif self.cycle >= self.max_cycles:
            self.running = False
            self.stop_reason = self._max_cycle_stop_reason(
                current_movement_count=movement_count,
            )
        else:
            self.stop_reason = "running"

        self._record_cycle_state(
            movement_count=movement_count,
            movement_by_group=movement_by_group,
            stable=stable,
        )

    def choose_move(self, piece: SakodaPiece) -> MoveDecision:
        stay_score = self.score_position(piece, piece.row, piece.column)
        adjacent_candidates = self.available_positions_within(piece.position, radius=1)
        adjacent_choice = self._best_strictly_better_candidate(
            piece=piece,
            candidates=adjacent_candidates,
            stay_score=stay_score,
        )
        if adjacent_choice is not None:
            destination, selected_score = adjacent_choice
            return MoveDecision(
                destination=destination,
                stay_score=stay_score,
                selected_score=selected_score,
                search_radius=1,
                candidate_count=len(adjacent_candidates),
                moved=True,
            )

        distance_two_candidates = self.available_positions_within(
            piece.position,
            radius=2,
        )
        if self.jump_rule == JUMP_RULE_NO_ADJACENT_AVAILABLE and adjacent_candidates:
            distance_two_candidates = []
        elif self.jump_rule == JUMP_RULE_ENDPOINT_ONLY:
            distance_two_candidates = self.available_distance_two_endpoints(
                piece.position
            )

        distance_two_choice = self._best_strictly_better_candidate(
            piece=piece,
            candidates=distance_two_candidates,
            stay_score=stay_score,
        )
        if distance_two_choice is not None:
            destination, selected_score = distance_two_choice
            return MoveDecision(
                destination=destination,
                stay_score=stay_score,
                selected_score=selected_score,
                search_radius=2,
                candidate_count=len(distance_two_candidates),
                moved=True,
            )

        return MoveDecision(
            destination=piece.position,
            stay_score=stay_score,
            selected_score=stay_score,
            search_radius=0,
            candidate_count=len(adjacent_candidates) + len(distance_two_candidates),
            moved=False,
        )

    def score_position(self, piece: SakodaPiece, row: int, column: int) -> float:
        score = 0.0
        for other in self.pieces:
            if other is piece:
                continue
            valence = piece.valence_toward(other)
            if valence == 0:
                continue
            squared_distance = (column - other.column) ** 2 + (row - other.row) ** 2
            if squared_distance <= 0:
                raise ValueError("A legal candidate position overlapped another piece.")
            score += valence / (squared_distance ** (1.0 / self.distance_weight))
        return score

    def available_positions_within(
        self,
        origin: Coordinate,
        *,
        radius: int,
    ) -> list[Coordinate]:
        origin_row, origin_column = origin
        positions: list[Coordinate] = []
        for row in range(
            max(1, origin_row - radius), min(self.rows, origin_row + radius) + 1
        ):
            for column in range(
                max(1, origin_column - radius),
                min(self.columns, origin_column + radius) + 1,
            ):
                candidate = (row, column)
                if candidate == origin:
                    continue
                if candidate in self._occupancy:
                    continue
                if max(abs(row - origin_row), abs(column - origin_column)) <= radius:
                    positions.append(candidate)
        positions.sort(
            key=lambda pos: (
                max(abs(pos[0] - origin_row), abs(pos[1] - origin_column)),
                pos[0],
                pos[1],
            )
        )
        return positions

    def available_distance_two_endpoints(self, origin: Coordinate) -> list[Coordinate]:
        origin_row, origin_column = origin
        offsets = (
            (-2, -2),
            (-2, 0),
            (-2, 2),
            (0, -2),
            (0, 2),
            (2, -2),
            (2, 0),
            (2, 2),
        )
        positions: list[Coordinate] = []
        for row_offset, column_offset in offsets:
            candidate = (origin_row + row_offset, origin_column + column_offset)
            if not self._in_bounds(candidate):
                continue
            if candidate in self._occupancy:
                continue
            positions.append(candidate)
        positions.sort(key=lambda pos: (pos[0], pos[1]))
        return positions

    def positions_snapshot(self) -> list[dict[str, int | str]]:
        return [piece.as_record() for piece in self._ordered_pieces()]

    def final_positions(self) -> list[dict[str, int | str]]:
        return self.positions_snapshot()

    def to_run_record(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario.name,
            "display_name": self.scenario.display_name,
            "source_caption": self.scenario.source_caption,
            "seed": self.seed_value,
            "board": {"rows": self.rows, "columns": self.columns},
            "group_size": self.group_size,
            "distance_weight": self.distance_weight,
            "max_cycles": self.max_cycles,
            "cycles_completed": self.cycle,
            "stop_reason": self.stop_reason,
            "attitudes": {
                SQUARES: {
                    "own_group": self.scenario.squares_own,
                    "other_group": self.scenario.squares_other,
                },
                CROSSES: {
                    "own_group": self.scenario.crosses_own,
                    "other_group": self.scenario.crosses_other,
                },
            },
            "movement_order": self.movement_order,
            "movement_order_description": self._movement_order_description(),
            "jump_rule": self.jump_rule,
            "jump_rule_description": self._jump_rule_description(),
            "tie_policy": "prefer_staying_over_equal_score_moves; random_ties_among_equal_moving_scores",
            "final_positions": self.final_positions(),
            "metrics_by_cycle": self.metrics_by_cycle,
            "positions_by_cycle": self.positions_by_cycle,
        }

    def ascii_board(self) -> str:
        return render_ascii_board(
            positions=self.positions_snapshot(),
            rows=self.rows,
            columns=self.columns,
        )

    def ascii_board_for_cycle(self, cycle: int) -> str:
        for snapshot in self.positions_by_cycle:
            if snapshot["cycle"] == cycle:
                return render_ascii_board(
                    positions=snapshot["positions"],
                    rows=self.rows,
                    columns=self.columns,
                )
        raise ValueError(f"No recorded positions for cycle {cycle}.")

    def _create_pieces(self, *, initial_positions: InitialPositionMap | None) -> None:
        if initial_positions is None:
            positions = self._random_initial_positions()
        else:
            positions = self._validated_initial_positions(initial_positions)

        for group in GROUPS:
            for piece_number in range(1, self.group_size + 1):
                row, column = positions[(group, piece_number)]
                piece = SakodaPiece(
                    self,
                    group=group,
                    piece_number=piece_number,
                    row=row,
                    column=column,
                    own_group_valence=self.scenario.own_valence_for(group),
                    other_group_valence=self.scenario.other_valence_for(group),
                )
                self.pieces.append(piece)
                self._occupancy[piece.position] = piece

    def _random_initial_positions(self) -> InitialPositionMap:
        all_cells = [
            (row, column)
            for row in range(1, self.rows + 1)
            for column in range(1, self.columns + 1)
        ]
        selected = self.random.sample(all_cells, self.group_size * len(GROUPS))
        positions: InitialPositionMap = {}
        index = 0
        for group in GROUPS:
            for piece_number in range(1, self.group_size + 1):
                positions[(group, piece_number)] = selected[index]
                index += 1
        return positions

    def _validated_initial_positions(
        self,
        initial_positions: InitialPositionMap,
    ) -> InitialPositionMap:
        expected_keys = {
            (group, piece_number)
            for group in GROUPS
            for piece_number in range(1, self.group_size + 1)
        }
        if set(initial_positions) != expected_keys:
            raise ValueError("initial_positions must define every group/piece number.")

        occupied: set[Coordinate] = set()
        positions: InitialPositionMap = {}
        for key, position in initial_positions.items():
            row, column = position
            if not self._in_bounds(position):
                raise ValueError(
                    f"Initial position out of bounds for {key}: {position}"
                )
            if position in occupied:
                raise ValueError(f"Duplicate initial position: {position}")
            occupied.add(position)
            positions[key] = (row, column)
        return positions

    def _best_strictly_better_candidate(
        self,
        *,
        piece: SakodaPiece,
        candidates: list[Coordinate],
        stay_score: float,
    ) -> tuple[Coordinate, float] | None:
        if not candidates:
            return None
        scored_candidates = [
            (candidate, self.score_position(piece, candidate[0], candidate[1]))
            for candidate in candidates
        ]
        best_score = max(score for _, score in scored_candidates)
        if not _strictly_better(best_score, stay_score):
            return None
        tied_best = [
            candidate
            for candidate, score in scored_candidates
            if _score_equal(score, best_score)
        ]
        return self.random.choice(tied_best), best_score

    def _movement_order_for_cycle(self) -> list[SakodaPiece]:
        if self.movement_order == MOVEMENT_ORDER_ALL_RANDOM:
            ordered_pieces = list(self.pieces)
            self.random.shuffle(ordered_pieces)
            return ordered_pieces

        ordered_pieces: list[SakodaPiece] = []
        for group in GROUPS:
            group_pieces = self._pieces_for_group(group)
            self.random.shuffle(group_pieces)
            ordered_pieces.extend(group_pieces)
        return ordered_pieces

    def _movement_order_description(self) -> str:
        if self.movement_order == MOVEMENT_ORDER_ALL_RANDOM:
            return "one_seeded_random_shuffle_of_all_pieces_per_cycle"
        return "seeded_random_order_within_each_group_squares_then_crosses_per_cycle"

    def _jump_rule_description(self) -> str:
        if self.jump_rule == JUMP_RULE_NO_ADJACENT_IMPROVEMENT:
            return (
                "adjacent_first_then_all_unoccupied_cells_within_chebyshev_distance_2_"
                "when_no_adjacent_strict_improvement"
            )
        if self.jump_rule == JUMP_RULE_NO_ADJACENT_AVAILABLE:
            return (
                "adjacent_first_then_all_unoccupied_cells_within_chebyshev_distance_2_"
                "only_when_no_adjacent_unoccupied_cell_is_available"
            )
        return (
            "adjacent_first_then_unoccupied_straight_or_diagonal_distance_2_endpoints_"
            "when_no_adjacent_strict_improvement"
        )

    def _move_piece(self, piece: SakodaPiece, destination: Coordinate) -> None:
        if not self._in_bounds(destination):
            raise ValueError(f"Destination out of bounds: {destination}")
        if destination in self._occupancy:
            raise ValueError(f"Destination occupied: {destination}")
        del self._occupancy[piece.position]
        piece.row, piece.column = destination
        self._occupancy[piece.position] = piece

    def _record_cycle_state(
        self,
        *,
        movement_count: int,
        movement_by_group: dict[str, int],
        stable: bool,
    ) -> None:
        positions = self.positions_snapshot()
        metrics = self._metrics_snapshot(
            movement_count=movement_count,
            movement_by_group=movement_by_group,
            stable=stable,
        )
        self.positions_by_cycle.append({"cycle": self.cycle, "positions": positions})
        self.metrics_by_cycle.append(metrics)

    def _metrics_snapshot(
        self,
        *,
        movement_count: int,
        movement_by_group: dict[str, int],
        stable: bool,
    ) -> dict[str, Any]:
        centroids = {group: self._centroid(group) for group in GROUPS}
        dispersions = {
            group: self._dispersion(group, centroids[group]) for group in GROUPS
        }
        centroid_distance = _euclidean(
            centroids[SQUARES]["row"],
            centroids[SQUARES]["column"],
            centroids[CROSSES]["row"],
            centroids[CROSSES]["column"],
        )
        pair_counts = self._adjacent_pair_counts()
        nearest = self._nearest_neighbor_metrics()
        edge_counts = {group: self._edge_count(group) for group in GROUPS}
        corner_counts = {group: self._corner_count(group) for group in GROUPS}
        center_distances = {
            group: self._mean_center_distance(group) for group in GROUPS
        }

        return {
            "cycle": self.cycle,
            "movement_count": movement_count,
            "squares_moves": movement_by_group.get(SQUARES, 0),
            "crosses_moves": movement_by_group.get(CROSSES, 0),
            "stable": stable,
            "stop_reason": self.stop_reason,
            "squares_centroid_row": centroids[SQUARES]["row"],
            "squares_centroid_column": centroids[SQUARES]["column"],
            "crosses_centroid_row": centroids[CROSSES]["row"],
            "crosses_centroid_column": centroids[CROSSES]["column"],
            "centroid_distance": centroid_distance,
            "squares_dispersion": dispersions[SQUARES],
            "crosses_dispersion": dispersions[CROSSES],
            "same_group_adjacent_pairs": pair_counts["same_group_adjacent_pairs"],
            "mixed_adjacent_pairs": pair_counts["mixed_adjacent_pairs"],
            "squares_edge_count": edge_counts[SQUARES],
            "crosses_edge_count": edge_counts[CROSSES],
            "squares_corner_count": corner_counts[SQUARES],
            "crosses_corner_count": corner_counts[CROSSES],
            "squares_mean_center_distance": center_distances[SQUARES],
            "crosses_mean_center_distance": center_distances[CROSSES],
            "checkerboard_alignment": self._checkerboard_alignment(),
            "mixed_nearest_neighbor_count": nearest["mixed_nearest_neighbor_count"],
            "mean_nearest_same_distance": nearest["mean_nearest_same_distance"],
            "mean_nearest_other_distance": nearest["mean_nearest_other_distance"],
        }

    def _centroid(self, group: str) -> dict[str, float]:
        pieces = self._pieces_for_group(group)
        return {
            "row": sum(piece.row for piece in pieces) / len(pieces),
            "column": sum(piece.column for piece in pieces) / len(pieces),
        }

    def _dispersion(self, group: str, centroid: dict[str, float]) -> float:
        pieces = self._pieces_for_group(group)
        squared_distance_sum = sum(
            (piece.column - centroid["column"]) ** 2
            + (piece.row - centroid["row"]) ** 2
            for piece in pieces
        )
        return math.sqrt(squared_distance_sum / len(pieces))

    def _pieces_for_group(self, group: str) -> list[SakodaPiece]:
        return [piece for piece in self.pieces if piece.group == group]

    def _ordered_pieces(self) -> list[SakodaPiece]:
        group_order = {group: index for index, group in enumerate(GROUPS)}
        return sorted(
            self.pieces,
            key=lambda piece: (group_order[piece.group], piece.piece_number),
        )

    def _adjacent_pair_counts(self) -> dict[str, int]:
        same_group = 0
        mixed = 0
        for index, first in enumerate(self.pieces):
            for second in self.pieces[index + 1 :]:
                if (
                    max(abs(first.row - second.row), abs(first.column - second.column))
                    > 1
                ):
                    continue
                if first.group == second.group:
                    same_group += 1
                else:
                    mixed += 1
        return {
            "same_group_adjacent_pairs": same_group,
            "mixed_adjacent_pairs": mixed,
        }

    def _edge_count(self, group: str) -> int:
        return sum(
            piece.row in (1, self.rows) or piece.column in (1, self.columns)
            for piece in self._pieces_for_group(group)
        )

    def _corner_count(self, group: str) -> int:
        corners = {
            (1, 1),
            (1, self.columns),
            (self.rows, 1),
            (self.rows, self.columns),
        }
        return sum(piece.position in corners for piece in self._pieces_for_group(group))

    def _mean_center_distance(self, group: str) -> float:
        center_row = (self.rows + 1) / 2
        center_column = (self.columns + 1) / 2
        pieces = self._pieces_for_group(group)
        return sum(
            _euclidean(piece.row, piece.column, center_row, center_column)
            for piece in pieces
        ) / len(pieces)

    def _checkerboard_alignment(self) -> float:
        even_squares = 0
        odd_squares = 0
        even_crosses = 0
        odd_crosses = 0
        for piece in self.pieces:
            even = (piece.row + piece.column) % 2 == 0
            if piece.group == SQUARES and even:
                even_squares += 1
            elif piece.group == SQUARES:
                odd_squares += 1
            elif piece.group == CROSSES and even:
                even_crosses += 1
            else:
                odd_crosses += 1
        aligned = max(even_squares + odd_crosses, odd_squares + even_crosses)
        return aligned / len(self.pieces)

    def _nearest_neighbor_metrics(self) -> dict[str, float | int]:
        nearest_same: list[float] = []
        nearest_other: list[float] = []
        mixed_nearest_neighbor_count = 0

        for piece in self.pieces:
            same_distances: list[float] = []
            other_distances: list[float] = []
            for other in self.pieces:
                if other is piece:
                    continue
                distance = _euclidean(piece.row, piece.column, other.row, other.column)
                if other.group == piece.group:
                    same_distances.append(distance)
                else:
                    other_distances.append(distance)
            nearest_same_distance = min(same_distances)
            nearest_other_distance = min(other_distances)
            nearest_same.append(nearest_same_distance)
            nearest_other.append(nearest_other_distance)
            if nearest_other_distance < nearest_same_distance or _score_equal(
                nearest_other_distance,
                nearest_same_distance,
            ):
                mixed_nearest_neighbor_count += 1

        return {
            "mixed_nearest_neighbor_count": mixed_nearest_neighbor_count,
            "mean_nearest_same_distance": sum(nearest_same) / len(nearest_same),
            "mean_nearest_other_distance": sum(nearest_other) / len(nearest_other),
        }

    def _in_bounds(self, position: Coordinate) -> bool:
        row, column = position
        return 1 <= row <= self.rows and 1 <= column <= self.columns

    def _max_cycle_stop_reason(
        self,
        *,
        current_movement_count: int | None = None,
    ) -> str:
        if self.scenario.unstable_expected:
            recent_movement_counts = [
                int(metric["movement_count"]) for metric in self.metrics_by_cycle[-9:]
            ]
            if current_movement_count is not None:
                recent_movement_counts.append(current_movement_count)
            if any(count > 0 for count in recent_movement_counts):
                return "persistent_or_recurrent_movement_max_cycles"
            return "max_cycles_reached_after_no_recent_movement"
        return "max_cycles_reached"


def render_ascii_board(
    *,
    positions: list[dict[str, int | str]],
    rows: int,
    columns: int,
) -> str:
    occupied = {
        (int(position["row"]), int(position["column"])): _symbol_for_position(position)
        for position in positions
    }
    header = "     " + " ".join(f"{column:>2}" for column in range(1, columns + 1))
    lines = [header]
    for row in range(1, rows + 1):
        cells = [
            f"{occupied.get((row, column), '..'):>2}"
            for column in range(1, columns + 1)
        ]
        lines.append(f"{row:>2} | " + " ".join(cells))
    return "\n".join(lines)


def _symbol_for_position(position: dict[str, int | str]) -> str:
    prefix = "S" if position["group"] == SQUARES else "X"
    return f"{prefix}{position['piece_number']}"


def _strictly_better(score: float, baseline: float) -> bool:
    return score > baseline + FLOAT_TOLERANCE


def _score_equal(first: float, second: float) -> bool:
    return math.isclose(
        first,
        second,
        rel_tol=FLOAT_TOLERANCE,
        abs_tol=FLOAT_TOLERANCE,
    )


def _euclidean(row_a: float, column_a: float, row_b: float, column_b: float) -> float:
    return math.sqrt((column_a - column_b) ** 2 + (row_a - row_b) ** 2)
