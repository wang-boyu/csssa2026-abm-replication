from __future__ import annotations

from random import Random


class BoundedSampleError(ValueError):
    """Raised when a bounded draw cannot be produced within the retry budget."""


def bounded_normal(
    rng: Random,
    mean: float,
    stddev: float,
    lower: float,
    upper: float,
    *,
    max_attempts: int = 10_000,
) -> float:
    if lower >= upper:
        raise ValueError("lower bound must be smaller than upper bound")
    if stddev <= 0:
        raise ValueError("stddev must be positive")

    for _ in range(max_attempts):
        value = rng.gauss(mean, stddev)
        if lower <= value <= upper:
            return value

    raise BoundedSampleError(
        f"normal draw stayed outside [{lower}, {upper}] after {max_attempts} attempts"
    )


def bounded_exponential(
    rng: Random,
    mean: float,
    lower: float,
    upper: float,
    *,
    max_attempts: int = 10_000,
) -> float:
    if lower >= upper:
        raise ValueError("lower bound must be smaller than upper bound")
    if mean <= 0:
        raise ValueError("mean must be positive")

    rate = 1.0 / mean
    for _ in range(max_attempts):
        value = rng.expovariate(rate)
        if lower <= value <= upper:
            return value

    raise BoundedSampleError(
        f"exponential draw stayed outside [{lower}, {upper}] after {max_attempts} attempts"
    )
