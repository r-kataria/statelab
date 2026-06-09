// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title BridgeableERC20Factory
/// @notice CREATE2 deployment helper that produces the same address on both
///         Anvil chains given the same ``(salt, creationCode)``.
///
/// Cross-chain address symmetry depends on three invariants:
///   1. The factory itself sits at the same address on both chains.
///   2. The ``salt`` is identical on both chains.
///   3. The ``creationCode`` (including constructor args) is identical on
///      both chains.
///
/// For (1) we rely on the harness's Docker-Anvil control: both chains are
/// freshly created, and the bridge deployer is the same EOA (derived from
/// the harness's deterministic mnemonic). The deployer's first few nonces
/// produce identical contract addresses on each chain by EIP-161 nonce-based
/// derivation, so deploying the factory at a fixed nonce on each side yields
/// the same factory address on both. The Python harness in a subsequent task
/// will deploy this factory as the *first* deployment by the bridge deployer
/// on each chain (nonce = 0 or some other agreed fixed nonce), guaranteeing
/// address parity.
///
/// (We deliberately do not depend on the "universal" CREATE2 proxy at
/// 0x4e59...956c because not every Anvil image pre-deploys it. The
/// deterministic-deployer-nonce route is simpler and fully under our
/// control.)
///
/// For (3) the harness must pass identical constructor args on both sides.
/// Since ``peerToken`` is the address being deployed (self-referential), the
/// pattern is:
///   - Deploy on chain A with ``peerToken_ = address(0)``.
///   - Deploy on chain B with ``peerToken_ = address(0)``: same
///     creationCode, same factory address, same salt, so same deployed
///     address as on chain A.
///   - Call ``setPeer(deployedAddress)`` on both sides to wire them
///     symmetrically.
///
/// (Alternatively the deployer can pre-compute the deterministic address
/// via ``predict`` and pass it as ``peerToken_`` on both sides, omitting the
/// ``setPeer`` step. Either approach is supported.)
contract BridgeableERC20Factory {
    event Deployed(address indexed addr, bytes32 indexed salt);

    /// @notice Predict the CREATE2 address for ``(salt, creationCode)``
    ///         deployed by *this factory*.
    function predict(bytes32 salt, bytes memory creationCode) external view returns (address) {
        return _predict(salt, keccak256(creationCode));
    }

    /// @notice Predict from a precomputed creation-code hash. Cheaper if the
    ///         caller already has it.
    function predictHash(bytes32 salt, bytes32 creationCodeHash) external view returns (address) {
        return _predict(salt, creationCodeHash);
    }

    /// @notice Deploy ``creationCode`` with ``salt`` via CREATE2.
    function deploy(bytes32 salt, bytes memory creationCode) external returns (address addr) {
        require(creationCode.length > 0, "Factory: empty code");
        // solhint-disable-next-line no-inline-assembly
        assembly {
            addr := create2(0, add(creationCode, 0x20), mload(creationCode), salt)
        }
        require(addr != address(0), "Factory: create2 failed");
        emit Deployed(addr, salt);
    }

    function _predict(bytes32 salt, bytes32 codeHash) internal view returns (address) {
        bytes32 raw = keccak256(
            abi.encodePacked(bytes1(0xff), address(this), salt, codeHash)
        );
        return address(uint160(uint256(raw)));
    }
}
