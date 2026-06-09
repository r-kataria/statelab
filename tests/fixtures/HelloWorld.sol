// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract HelloWorld {
    uint256 private value;
    address public lastSetter;

    function setValue(uint256 v) external {
        value = v;
        lastSetter = msg.sender;
    }

    function getValue() external view returns (uint256) {
        return value;
    }
}
