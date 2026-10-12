"""Configuration owned by the paying client."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from web3 import Web3


@dataclass(frozen=True, slots=True)
class ClientPaymentPolicy:
    """The payer identity and maximum amount accepted for one invocation."""

    network_deployment: Path
    payer: str
    max_amount_atomic: str

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
        )
