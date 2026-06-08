"""Deterministic simulation kernels for Wonderlab scene blueprints."""

from __future__ import annotations

from dataclasses import dataclass


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class SimulationSnapshot:
    label: str
    value: float
    unit: str
    explanation: str


def barter_success_rate(
    wants_overlap: float,
    trust: float,
    market_size: int,
) -> SimulationSnapshot:
    """Estimate how often barter trades clear in a toy market.

    This is an educational model, not an economic forecast. It encodes the
    mental model that barter needs coincidence of wants, trust, and enough
    participants to find a match.
    """
    overlap = _clamp(wants_overlap)
    trust_score = _clamp(trust)
    size_score = _clamp((market_size - 2) / 98)
    success = _clamp((0.48 * overlap) + (0.32 * trust_score) + (0.20 * size_score))
    return SimulationSnapshot(
        label="Trade success",
        value=round(success * 100, 1),
        unit="percent",
        explanation=(
            "Barter works when wants overlap, trust is high, and the market is "
            "large enough to find a counterparty."
        ),
    )


def bank_run_resilience(
    reserve_ratio: float,
    daily_withdrawal_rate: float,
    confidence_shock: float,
) -> SimulationSnapshot:
    """Estimate days before liquid reserves are exhausted in a toy bank run."""
    reserves = _clamp(reserve_ratio)
    withdrawals = max(0.01, _clamp(daily_withdrawal_rate))
    shock = _clamp(confidence_shock)
    effective_outflow = withdrawals * (1 + shock)
    days = reserves / effective_outflow
    return SimulationSnapshot(
        label="Reserve runway",
        value=round(days, 1),
        unit="days",
        explanation=(
            "A bank run is a speed problem: even a bank with assets can fail if "
            "liquid reserves leave faster than assets can be sold or financed."
        ),
    )


def inflation_pressure(
    money_growth: float,
    goods_growth: float,
    velocity_change: float,
    expectations_shock: float,
) -> SimulationSnapshot:
    """Toy inflation pressure index from monetary, real, and expectation inputs."""
    pressure = (
        money_growth
        - goods_growth
        + (0.65 * velocity_change)
        + (0.85 * expectations_shock)
    )
    return SimulationSnapshot(
        label="Inflation pressure",
        value=round(pressure, 2),
        unit="index",
        explanation=(
            "The model keeps the key lesson visible: prices respond to money, "
            "goods, spending speed, and expectations together."
        ),
    )
