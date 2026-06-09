// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title ERC20
/// @notice Minimal 18-decimals ERC-20 for the thesis on-chain stack, with two
///         harness-specific changes:
///           1. The constructor mints ``initialSupply`` to ``msg.sender`` so
///              ``ERC20.deploy(chain, name, sym, supply=...)`` needs no second
///              mint transaction.
///           2. ``mint`` is public so tests can fund actors mid-run.
///
///         No ownership / pausing / blocklists; this is for local runs only.
///         transfer / transferFrom keep standard semantics including the
///         type(uint256).max infinite-allowance shortcut.
contract ERC20 {
    string public name;
    string public symbol;
    uint8 public immutable decimals;

    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    constructor(string memory name_, string memory symbol_, uint256 initialSupply) {
        name = name_;
        symbol = symbol_;
        decimals = 18;
        if (initialSupply > 0) {
            _mint(msg.sender, initialSupply);
        }
    }

    // --- Mutators ---

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transfer(address to, uint256 value) external returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        if (allowed != type(uint256).max) {
            require(allowed >= value, "ERC20: insufficient allowance");
            unchecked {
                allowance[from][msg.sender] = allowed - value;
            }
        }
        _transfer(from, to, value);
        return true;
    }

    /// @notice Public mint for tests. Not for production use.
    function mint(address to, uint256 value) external {
        _mint(to, value);
    }

    // --- Internals ---

    function _transfer(address from, address to, uint256 value) internal {
        require(to != address(0), "ERC20: to=0");
        require(balanceOf[from] >= value, "ERC20: insufficient balance");
        unchecked {
            balanceOf[from] -= value;
            balanceOf[to] += value;
        }
        emit Transfer(from, to, value);
    }

    function _mint(address to, uint256 value) internal {
        require(to != address(0), "ERC20: mint to=0");
        totalSupply += value;
        unchecked {
            balanceOf[to] += value;
        }
        emit Transfer(address(0), to, value);
    }

    function _burn(address from, uint256 value) internal {
        require(balanceOf[from] >= value, "ERC20: burn exceeds balance");
        unchecked {
            balanceOf[from] -= value;
        }
        totalSupply -= value;
        emit Transfer(from, address(0), value);
    }
}
