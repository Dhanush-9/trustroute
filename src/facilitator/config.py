"""Runtime configuration for the independent local facilitator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from web3 import Web3


@dataclass(frozen=True, slots=True)
class LocalFacilitatorConfig:
    network_deployment: Path
    expected_signer: str
    host: str
    port: int
    public_url: str

    @classmethod
    def from_path(cls, path: Path | str) -> "LocalFacilitatorConfig":
        source_path = Path(path).resolve()
        data = json.loads(source_path.read_text(encoding="utf-8"))
        network_path = Path(str(data["networkDeployment"]))
        if not network_path.is_absolute():
            network_path = (source_path.parent / network_path).resolve()

        port = int(data["port"])
        if not 1 <= port <= 65535:
            raise ValueError("facilitator port must be between 1 and 65535")

        public_url = str(data["publicUrl"]).rstrip("/")
        parsed = urlsplit(public_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("facilitator publicUrl must be an HTTP URL")

        return cls(
            network_deployment=network_path,
            expected_signer=Web3.to_checksum_address(str(data["expectedSigner"])),
            host=str(data["host"]),
            port=port,
            public_url=public_url,
        )
