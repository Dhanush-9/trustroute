"""Buyer-side x402 transport with identity and budget checks."""

from __future__ import annotations

import os

import httpx
from eth_account import Account
from web3 import Web3
from x402 import AbortResult, x402Client
from x402.http.clients.httpx import x402_httpx_transport
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact import register_exact_evm_client

from client.config import ClientPaymentPolicy
from client.output import heading
from x402_support.network import PaymentNetwork


BALANCE_OF_ABI = [
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]


class PaymentPolicyError(ValueError):
    """An advertised skill price is incompatible with the client policy."""


def validate_advertised_price(
    network: PaymentNetwork,
    policy: ClientPaymentPolicy,
    *,
    amount_atomic: str,
    advertised_network: str,
    advertised_asset: str,
) -> None:
    """Reject unaffordable or wrong-network listings before task input."""

    if advertised_network != network.network:
        raise PaymentPolicyError(
            f"agent advertises {advertised_network}, client requires {network.network}"
        )
    if advertised_asset.lower() != network.asset.lower():
        raise PaymentPolicyError("advertised payment asset differs from client policy")
    if int(amount_atomic) > int(policy.max_amount_atomic):
        offered = network.display_amount(amount_atomic)
        maximum = network.display_amount(policy.max_amount_atomic)
        raise PaymentPolicyError(
            f"advertised price {offered} {network.asset_symbol} exceeds "
            f"client maximum {maximum} {network.asset_symbol}"
        )


def _token_balance(web3: Web3, asset: str, account: str) -> int:
    token = web3.eth.contract(
        address=web3.to_checksum_address(asset),
        abi=BALANCE_OF_ABI,
    )
    return int(token.functions.balanceOf(web3.to_checksum_address(account)).call())


def build_paying_transport(
    network: PaymentNetwork,
    policy: ClientPaymentPolicy,
    *,
    expected_recipient: str,
    expected_amount_atomic: str,
) -> httpx.AsyncBaseTransport:
    """Sign only identity-bound offers matching the advertised skill price."""

    private_key = os.environ.get("TRUSTROUTE_PAYER_PRIVATE_KEY")
    if not private_key:
        raise RuntimeError("TRUSTROUTE_PAYER_PRIVATE_KEY is required")

    account = Account.from_key(private_key)
    if account.address.lower() != policy.payer.lower():
        raise ValueError("payer key does not match the configured payer address")

    expected_recipient = Web3.to_checksum_address(expected_recipient)
    if int(expected_recipient, 16) == 0:
        raise ValueError("ERC-8004 agentWallet is unset")

    web3 = Web3(Web3.HTTPProvider(network.rpc_url))
    if not web3.is_connected() or web3.eth.chain_id != network.chain_id:
        raise ConnectionError("cannot connect to the expected payment network")

    client = x402Client()
    register_exact_evm_client(
        client,
        EthAccountSigner(account),
        networks=network.network,
    )
    client.set_spend_controls(
        {
            "allowed_assets": [
                {
                    "network": network.network,
                    "asset": network.asset,
                    "max_amount_per_payment": policy.max_amount_atomic,
                }
            ]
        }
    )

    balances_before: dict[str, int] = {}

    def enforce_offer(context):
        requirement = context.selected_requirements
        offered_recipient = Web3.to_checksum_address(
            requirement.pay_to
        )
        if offered_recipient != expected_recipient:
            print("Budget decision: rejected")
            print(f"Reason: x402 recipient {offered_recipient}")
            print(f"does not match ERC-8004 agentWallet {expected_recipient}\n")
            return AbortResult(reason="x402 recipient does not match ERC-8004 agentWallet")

        if str(requirement.amount) != expected_amount_atomic:
            print("Skill-price binding: rejected")
            return AbortResult(
                reason="x402 amount does not match the AgentCard skill price"
            )

        print("Identity recipient: verified")
        print("Skill-price binding: verified")
        print("Budget decision: accepted")
        return None

    def show_authorization(context) -> None:
        requirement = context.selected_requirements
        authorization = context.payment_payload.payload["authorization"]
        balances_before["payer"] = _token_balance(
            web3, network.asset, policy.payer
        )
        balances_before["recipient"] = _token_balance(
            web3, network.asset, expected_recipient
        )

        heading("X402 PAYMENT")
        print("Challenge: HTTP 402 Payment Required")
        print(f"x402 version: {context.payment_payload.x402_version}")
        print(f"Payment scheme: {requirement.scheme}")
        print(f"Payment network: {requirement.network}")
        print(
            "Offered price: "
            f"{network.display_amount(requirement.amount)} {network.asset_symbol} "
            f"({requirement.amount} atomic units)"
        )
        print(f"Payment asset: {requirement.asset}")
        print(f"Payer: {authorization['from']}")
        print(f"Recipient: {authorization['to']}")
        print("Payment authorization: EIP-712 signature created")
        print(f"Payer balance before: {balances_before['payer']}")
        print(f"Recipient balance before: {balances_before['recipient']}\n")

    def show_settlement(context):
        settlement = context.settle_response
        if settlement is None:
            print(f"x402 settlement: unavailable ({context.error})")
            return None

        payer_after = _token_balance(web3, network.asset, policy.payer)
        recipient_after = _token_balance(web3, network.asset, expected_recipient)
        print(f"x402 settlement: {'successful' if settlement.success else 'failed'}")
        print(f"Settlement transaction: {settlement.transaction}")
        print(f"Payer balance after: {payer_after}")
        print(f"Recipient balance after: {recipient_after}")
        if balances_before:
            print(f"Amount transferred: {balances_before['payer'] - payer_after}")
        print()
        return None

    client.on_before_payment_creation(enforce_offer)
    client.on_after_payment_creation(show_authorization)
    client.on_payment_response(show_settlement)

    return x402_httpx_transport(client, transport=httpx.AsyncHTTPTransport())
