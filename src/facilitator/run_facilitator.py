"""Start the independent local x402 facilitator service."""

import argparse
from pathlib import Path

import uvicorn

from facilitator.app import build_facilitator_app
from facilitator.config import LocalFacilitatorConfig
from x402_support.network import PaymentNetwork


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/facilitator/local.json"),
        help="facilitator configuration file",
    )
    args = parser.parse_args()

    config = LocalFacilitatorConfig.from_path(args.config)
    network = PaymentNetwork.from_path(config.network_deployment)
    app = build_facilitator_app(config, network)

    print(f"Facilitator: {config.public_url}")
    print(f"Settlement signer: {config.expected_signer}")
    print(f"Payment network: {network.network}")
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
