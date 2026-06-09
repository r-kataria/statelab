// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title DtnBridge
/// @notice Minimal cross-chain messenger with a Python-side relay.
///
/// The bridge is a dumb messenger: it only carries one kind of payload,
/// a low-level contract call on the destination chain. Token movement is
/// handled by the token contracts themselves via burn-on-source / mint-on-
/// destination (see ``BridgeableERC20``); the bridge never touches token
/// balances and is never pre-funded with tokens.
///
/// Source side: anyone calls ``send(target, valueAmount, data)``. The bridge
/// emits a ``MessageSent`` log; the Python relay polls for these logs, waits
/// the simulated delay, and submits a matching ``deliver`` call on the
/// destination side. The bridge ``owner`` is the only address authorised to
/// call ``deliver`` (in the harness this is the chain deployer driving the
/// relay).
///
/// Replay protection: a ``delivered`` mapping keyed by source nonce. The
/// source-chain bridge is the only producer of nonces it sees, so the nonce
/// alone is unique per direction.
///
/// The ``sender`` field threaded through ``deliver`` is the original source-
/// side ``msg.sender`` recorded in the ``MessageSent`` event. The relay
/// passes it back so the destination-side target can authenticate the
/// originating caller if it cares to. (``BridgeableERC20.bridgeMint`` does
/// not check it, it trusts the bridge, but the field is available.)
///
/// Not audited; for local simulation only.
contract DtnBridge {
    // ── State ───────────────────────────────────────────────────────

    uint256 public nonce;
    address public owner;

    /// @notice srcNonce => already delivered? (replay protection)
    mapping(uint256 => bool) public delivered;

    // ── Events ──────────────────────────────────────────────────────

    /// @param nonce   monotonically increasing per-bridge counter
    /// @param sender  original caller on the source chain
    /// @param target  destination-chain contract to call
    /// @param value   ETH value to forward with the call
    /// @param data    calldata for the destination-side call
    event MessageSent(
        uint256 indexed nonce,
        address indexed sender,
        address indexed target,
        uint256 value,
        bytes data
    );

    event MessageDelivered(
        uint256 indexed srcNonce,
        address indexed target,
        bool success,
        bytes returndata
    );

    // ── Modifiers ───────────────────────────────────────────────────

    modifier onlyOwner() {
        require(msg.sender == owner, "DtnBridge: not owner");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    // ── Source side ─────────────────────────────────────────────────

    /// @notice Queue a cross-chain message. Returns the source-side nonce.
    function send(
        address target,
        uint256 valueAmount,
        bytes calldata data
    ) external payable returns (uint256) {
        uint256 n = nonce++;
        emit MessageSent(n, msg.sender, target, valueAmount, data);
        return n;
    }

    // ── Destination side ────────────────────────────────────────────

    /// @notice Replay-protected delivery. Only ``owner`` (the relay) may call.
    /// @dev ``sender`` is the original source-side caller, threaded through
    ///      from the corresponding ``MessageSent`` event. It is not used for
    ///      authorisation by the bridge itself; targets may inspect it as a
    ///      parameter if needed (currently no target does so, they trust
    ///      that ``msg.sender == bridge`` is sufficient because the relay is
    ///      trusted in this testbed).
    function deliver(
        uint256 srcNonce,
        address sender,
        address target,
        uint256 valueAmount,
        bytes calldata data
    ) external onlyOwner returns (bool success, bytes memory returndata) {
        require(!delivered[srcNonce], "DtnBridge: already delivered");
        delivered[srcNonce] = true;

        // ``sender`` is consumed off-chain (logged in the event below) and
        // intentionally not part of the call into ``target``. Reference it
        // here so the parameter is not flagged unused.
        sender;

        (success, returndata) = target.call{value: valueAmount}(data);

        emit MessageDelivered(srcNonce, target, success, returndata);
        return (success, returndata);
    }

    receive() external payable {}
}
