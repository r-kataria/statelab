// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title Counter
/// @notice Placeholder contract for the StateLab plugin template. Replace it
/// with your own; the plugin in ../__init__.py shows how it gets deployed,
/// called, and recorded.
contract Counter {
    uint256 public count;

    function add(uint256 n) external {
        count += n;
    }
}
