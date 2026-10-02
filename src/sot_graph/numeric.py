"""Numeric domains shared by command and protocol boundaries."""

from __future__ import annotations

import math
from typing import Any


def integer(value: Any, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        domain = "a positive integer" if minimum == 1 else f"an integer >= {minimum}"
        raise ValueError(f"{name} must be {domain} (got {value!r})")
    return value


def finite_number(value: Any, name: str, *, minimum: float = 0,
                  maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number) or number < minimum or (maximum is not None and number > maximum):
        upper = f" and <= {maximum}" if maximum is not None else ""
        raise ValueError(f"{name} must be finite, >= {minimum}{upper}")
    return number
