"""Read the chain and token deployment produced by the local deploy script."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from web3 import Web3


@dataclass(frozen=True, slots=True)
class PaymentNetwork:
    """Network-level data shared by clients, agents, and facilitators.

    Agent prices, payment recipients, wallets, and private keys deliberately do
    not belong here. They are policies or secrets owned by individual actors.
    """

    rpc_url: str
    chain_id: int
    network: str
    asset: str
    asset_name: str
    asset_symbol: str
    asset_version: str
    asset_decimals: int

    @classmethod
    def from_path(cls, path: Path | str) -> "PaymentNetwork":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        deployment = cls(
            rpc_url=str(data["rpcUrl"]),
            chain_id=int(data["chainId"]),
            network=str(data["network"]),
            asset=Web3.to_checksum_address(str(data["asset"])),
            asset_name=str(data["assetName"]),
            asset_symbol=str(data["assetSymbol"]),
            asset_version=str(data["assetVersion"]),
            asset_decimals=int(data["assetDecimals"]),
        )

        if deployment.network != f"eip155:{deployment.chain_id}":
            raise ValueError("payment deployment has an inconsistent CAIP-2 network")
        if not 0 <= deployment.asset_decimals <= 18:
            raise ValueError("payment asset decimals must be between 0 and 18")
        return deployment

    def display_amount(self, atomic_amount: str) -> str:
        """Convert an integer token amount into a display value."""

        if not atomic_amount.isdigit():
            raise ValueError("token amount must be a non-negative integer string")
        amount = Decimal(atomic_amount) / Decimal(10**self.asset_decimals)
        return f"{amount:.{self.asset_decimals}f}".rstrip("0").rstrip(".")
