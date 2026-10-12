// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/EIP712.sol";

/**
 * A local-only six-decimal token with EIP-3009 authorization support.
 *
 * Real x402 deployments normally use an existing stablecoin such as USDC.
 * TrustRoute deploys this small token to Hardhat so the full payment flow is
 * reproducible without testnet funds or an external faucet.
 */
contract TrustRouteMockUSDC is ERC20, EIP712 {
    bytes32 private constant TRANSFER_WITH_AUTHORIZATION_TYPEHASH = keccak256(
        "TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    );

    mapping(address authorizer => mapping(bytes32 nonce => bool used))
        public authorizationState;

    event AuthorizationUsed(address indexed authorizer, bytes32 indexed nonce);

    constructor(address initialHolder, uint256 initialSupply)
        ERC20("TrustRoute USD Coin", "trUSDC")
        EIP712("TrustRoute USD Coin", "2")
    {
        _mint(initialHolder, initialSupply);
    }

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    function version() external pure returns (string memory) {
        return "2";
    }

    /**
     * Transfer tokens using a one-time EIP-712 signature from `from`.
     * Anyone may submit the authorization; in x402 the facilitator submits it
     * and pays the transaction gas.
     */
    function transferWithAuthorization(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external {
        require(block.timestamp > validAfter, "authorization not active");
        require(block.timestamp < validBefore, "authorization expired");
        require(!authorizationState[from][nonce], "authorization already used");

        bytes32 structHash = keccak256(
            abi.encode(
                TRANSFER_WITH_AUTHORIZATION_TYPEHASH,
                from,
                to,
                value,
                validAfter,
                validBefore,
                nonce
            )
        );
        address signer = ECDSA.recover(_hashTypedDataV4(structHash), v, r, s);
        require(signer == from, "invalid authorization signature");

        authorizationState[from][nonce] = true;
        emit AuthorizationUsed(from, nonce);
        _transfer(from, to, value);
    }
}
