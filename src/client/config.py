"""Configuration owned by the paying client."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from web3 import Web3


def _number(data: dict, field: str) -> float:
    value = data.get(field)
    if isinstance(value, bool):
        raise ValueError(f"client selection field {field!r} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"client selection field {field!r} must be numeric"
        ) from error
    if not math.isfinite(result):
        raise ValueError(f"client selection field {field!r} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class SelectionPolicy:
    """Client-owned weights and cold-start assumptions for agent ranking."""

    reputation_weight: float
    semantic_weight: float
    price_weight: float
    prior_score: float
    prior_weight: float
    cold_start_bonus: float

    @classmethod
    def from_data(cls, data: object) -> "SelectionPolicy":
        if not isinstance(data, dict):
            raise ValueError("client configuration needs a selection object")

        policy = cls(
            reputation_weight=_number(data, "reputationWeight"),
            semantic_weight=_number(data, "semanticWeight"),
            price_weight=_number(data, "priceWeight"),
            prior_score=_number(data, "priorScore"),
            prior_weight=_number(data, "priorWeight"),
            cold_start_bonus=_number(data, "coldStartBonus"),
        )
        weights = (
            policy.reputation_weight,
            policy.semantic_weight,
            policy.price_weight,
        )
        if (
            any(weight < 0 for weight in weights)
            or abs(sum(weights) - 1) > 1e-9
        ):
            raise ValueError(
                "client selection weights must be non-negative and sum to 1"
            )
        if not 0 <= policy.prior_score <= 100:
            raise ValueError("client selection priorScore must be in [0, 100]")
        if policy.prior_weight <= 0:
            raise ValueError("client selection priorWeight must be positive")
        if not 0 <= policy.cold_start_bonus <= 1:
            raise ValueError("client selection coldStartBonus must be in [0, 1]")
        return policy


@dataclass(frozen=True, slots=True)
class ClientPaymentPolicy:
    """The payer identity and maximum amount accepted for one invocation."""

    network_deployment: Path
    payer: str
    max_amount_atomic: str
    selection: SelectionPolicy

    @classmethod
    def from_path(cls, path: Path | str) -> "ClientPaymentPolicy":
        source_path = Path(path).resolve()
        data = json.loads(source_path.read_text(encoding="utf-8"))
        network_path = Path(str(data["networkDeployment"]))
        if not network_path.is_absolute():
            network_path = (source_path.parent / network_path).resolve()

        maximum = str(data["maxAmountAtomic"])
        if not maximum.isdigit() or int(maximum) <= 0:
            raise ValueError("client maxAmountAtomic must be a positive integer")

        return cls(
            network_deployment=network_path,
            payer=Web3.to_checksum_address(str(data["payer"])),
            max_amount_atomic=maximum,
            selection=SelectionPolicy.from_data(data.get("selection")),
        )
