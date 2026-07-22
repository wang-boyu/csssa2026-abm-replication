from __future__ import annotations

from contextlib import ExitStack
import importlib
import inspect
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import slumulation

STATE_EXPORTS = (
    "PatchState",
    "WorldSummary",
    "WorldState",
    "build_empty_world",
    "is_central_ward",
    "is_peripheral_ward",
    "ward_for_coordinate",
)

EXPECTED_COORDINATES = frozenset((x, y) for x in range(-25, 26) for y in range(-25, 26))

REPRESENTATIVE_WARD_COORDINATES = {
    (-25, -25): 1,
    (0, -25): 2,
    (25, -25): 3,
    (-25, 0): 4,
    (0, 0): 5,
    (25, 0): 6,
    (-25, 25): 7,
    (0, 25): 8,
    (25, 25): 9,
    (-8, -8): 5,
    (8, 8): 5,
}

EXPECTED_PATCH_DEFAULTS = {
    "num_units": 1,
    "available": True,
    "occupied": False,
    "num_occupants": 0,
    "slum_occupants": 0,
    "slum": False,
    "rent": 0,
    "rent_payable": 0,
    "resicat": 0,
}

FORBIDDEN_PUBLIC_API_NAMES = (
    "Slumulate",
    "slumulate",
    "step",
    "SlumulationModel",
    "SlumulationRunner",
    "SlumulationValidator",
    "SlumulationComparison",
    "SlumulationOutputWriter",
    "OutputWriter",
    "run_slumulation",
    "run_simulation",
    "simulate_slumulation",
    "validate_slumulation",
    "compare_slumulation",
    "write_slumulation_output",
    "write_output",
    "validator",
    "comparison",
    "output_writer",
    "Slumulation",
    "SlumulationStep",
    "MesaModel",
    "MesaSlumulationModel",
    "SlumulationMesaModel",
    "Model",
    "Runner",
    "Validator",
    "Comparison",
    "Simulation",
    "simulation",
)


def _state_api() -> SimpleNamespace:
    state = importlib.import_module("slumulation.state")

    missing_from_state = [name for name in STATE_EXPORTS if not hasattr(state, name)]
    if missing_from_state:
        raise AssertionError(
            "slumulation.state is missing expected public exports: "
            f"{missing_from_state!r}"
        )

    missing_from_package = [
        name for name in STATE_EXPORTS if not hasattr(slumulation, name)
    ]
    if missing_from_package:
        raise AssertionError(
            f"slumulation is missing expected re-exports: {missing_from_package!r}"
        )

    for name in STATE_EXPORTS:
        if getattr(slumulation, name) is not getattr(state, name):
            raise AssertionError(f"slumulation.{name} must re-export state.{name}")

    exports = {name: getattr(slumulation, name) for name in STATE_EXPORTS}
    return SimpleNamespace(module=state, **exports)


def _patch_default_snapshot(patch) -> tuple[tuple[str, object], ...]:
    return tuple((name, getattr(patch, name)) for name in EXPECTED_PATCH_DEFAULTS)


def _world_snapshot(world) -> tuple[tuple[tuple[int, int], int, tuple], ...]:
    return tuple(
        (coordinate, patch.ward, _patch_default_snapshot(patch))
        for coordinate, patch in sorted(world.patches.items())
    )


class SlumulationStateTests(unittest.TestCase):
    def test_state_helpers_are_exported_from_package_and_state_module(self) -> None:
        api = _state_api()

        self.assertTrue(inspect.isclass(api.PatchState))
        self.assertTrue(inspect.isclass(api.WorldSummary))
        self.assertTrue(inspect.isclass(api.WorldState))
        self.assertTrue(callable(api.build_empty_world))
        self.assertTrue(callable(api.is_central_ward))
        self.assertTrue(callable(api.is_peripheral_ward))
        self.assertTrue(callable(api.ward_for_coordinate))

    def test_empty_world_has_exact_netlogo_coordinate_surface(self) -> None:
        api = _state_api()

        world = api.build_empty_world()

        self.assertIsInstance(world, api.WorldState)
        self.assertEqual(len(world.patches), 2601)
        self.assertEqual(world.patch_count, 2601)
        self.assertEqual(set(world.patches), EXPECTED_COORDINATES)
        self.assertEqual(world.households, [])
        self.assertEqual(world.developers, [])

    def test_ward_assignment_matches_representative_coordinates(self) -> None:
        api = _state_api()
        world = api.build_empty_world()

        for coordinate, expected_ward in REPRESENTATIVE_WARD_COORDINATES.items():
            with self.subTest(coordinate=coordinate):
                x, y = coordinate
                self.assertEqual(api.ward_for_coordinate(x, y), expected_ward)
                self.assertEqual(world.patches[coordinate].ward, expected_ward)

        for coordinate, patch_state in world.patches.items():
            with self.subTest(coordinate=coordinate):
                self.assertEqual(
                    patch_state.ward,
                    api.ward_for_coordinate(*coordinate),
                )

    def test_ward_five_is_central_and_all_other_wards_are_peripheral(self) -> None:
        api = _state_api()

        for ward in range(1, 10):
            with self.subTest(ward=ward):
                self.assertIs(api.is_central_ward(ward), ward == 5)
                self.assertIs(api.is_peripheral_ward(ward), ward != 5)

    def test_empty_patch_defaults_match_source_setup_defaults(self) -> None:
        api = _state_api()
        world = api.build_empty_world()

        for coordinate, patch_state in world.patches.items():
            with self.subTest(coordinate=coordinate):
                self.assertIsInstance(patch_state, api.PatchState)
                self.assertEqual(
                    dict(_patch_default_snapshot(patch_state)),
                    EXPECTED_PATCH_DEFAULTS,
                )

    def test_empty_world_construction_is_deterministic_and_setup_only(self) -> None:
        api = _state_api()

        self.assertEqual(tuple(inspect.signature(api.build_empty_world).parameters), ())

        random_functions = (
            "random.random",
            "random.uniform",
            "random.randrange",
            "random.choice",
            "random.choices",
            "random.sample",
            "random.shuffle",
        )
        with ExitStack() as stack:
            for target in random_functions:
                stack.enter_context(
                    patch(
                        target,
                        side_effect=AssertionError(
                            f"build_empty_world must not call {target}"
                        ),
                    )
                )
            first_world = api.build_empty_world()
            second_world = api.build_empty_world()

        self.assertEqual(_world_snapshot(first_world), _world_snapshot(second_world))

        for method_name in ("step", "Slumulate", "slumulate", "run", "simulate"):
            self.assertFalse(hasattr(first_world, method_name), method_name)

    def test_no_premature_simulation_or_validation_api_is_public(self) -> None:
        api = _state_api()
        world = api.build_empty_world()
        namespaces = (
            ("slumulation", slumulation),
            ("slumulation.state", api.module),
            ("WorldState", world),
        )

        for namespace_name, namespace in namespaces:
            exported_names = set(getattr(namespace, "__all__", ()))
            for api_name in FORBIDDEN_PUBLIC_API_NAMES:
                with self.subTest(namespace=namespace_name, api_name=api_name):
                    self.assertFalse(hasattr(namespace, api_name), api_name)
                    self.assertNotIn(api_name, exported_names)


if __name__ == "__main__":
    unittest.main()
