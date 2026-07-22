from __future__ import annotations

import unittest
from random import Random

from yatasterps.randomness import (
    BoundedSampleError,
    bounded_exponential,
    bounded_normal,
)


class RandomnessTests(unittest.TestCase):
    def test_bounded_normal_returns_value_within_bounds(self) -> None:
        value = bounded_normal(Random(42), 0.5, 0.1, 0.2, 0.8)
        self.assertGreaterEqual(value, 0.2)
        self.assertLessEqual(value, 0.8)

    def test_bounded_exponential_returns_value_within_bounds(self) -> None:
        value = bounded_exponential(Random(42), 0.3, 0.01, 0.99)
        self.assertGreaterEqual(value, 0.01)
        self.assertLessEqual(value, 0.99)

    def test_invalid_randomness_arguments_raise_value_error(self) -> None:
        with self.assertRaises(ValueError):
            bounded_normal(Random(1), 0.5, 0.0, 0.1, 0.9)

        with self.assertRaises(ValueError):
            bounded_exponential(Random(1), 0.0, 0.1, 0.9)

        with self.assertRaises(ValueError):
            bounded_normal(Random(1), 0.5, 0.1, 0.9, 0.1)

        with self.assertRaises(ValueError):
            bounded_exponential(Random(1), 0.5, 0.9, 0.1)

    def test_zero_attempt_budget_raises_bounded_sample_error(self) -> None:
        with self.assertRaises(BoundedSampleError):
            bounded_normal(Random(1), 0.5, 0.1, 0.1, 0.9, max_attempts=0)

        with self.assertRaises(BoundedSampleError):
            bounded_exponential(Random(1), 0.5, 0.1, 0.9, max_attempts=0)


if __name__ == "__main__":
    unittest.main()
