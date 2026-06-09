// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IDtnBridge {
    function send(address target, uint256 valueAmount, bytes calldata data)
        external
        payable
        returns (uint256);
}

/// @title BridgeableERC20
/// @notice ERC-20 with cross-chain burn-on-source / mint-on-destination owned
///         by the *token contract itself*.
///
/// Deployment pattern: the same contract is deployed at the *same address* on
/// both chains via ``BridgeableERC20Factory`` (CREATE2). Each side is wired
/// to its local bridge and to the peer-token address on the other chain,
/// which, by construction, equals its own address.
///
/// User flow for cross-chain transfer:
///   1. ``bridgeSend(recipient, amount)`` burns ``amount`` from the caller on
///      the source chain and dispatches a bridge message whose payload is
///      ``this.bridgeMint(recipient, amount)`` targeted at the peer token.
///   2. The relay delivers the message on the destination chain. The peer
///      token's ``bridgeMint`` (only callable by the local bridge) mints
///      ``amount`` to ``recipient``.
///
/// The bridge is trusted (we control the relay in this testbed), so
/// ``bridgeMint`` only checks ``msg.sender == bridge`` and not the original
/// source-side sender.
///
/// Trust model: ``bridgeMint`` is gated on ``msg.sender == bridge``, so this
/// contract trusts the *bridge contract* not to mint without authority.
/// The *bridge contract*, in turn, trusts the *relay* in this codebase's
/// trusted-relay verification model (see thesis §5.4). For other bridge
/// verification models (optimistic, ZK), the bridge would cryptographically
/// verify the source-side emission before invoking ``bridgeMint``; the
/// token contract is unchanged either way.
///
/// Not audited; for local simulation only.
contract BridgeableERC20 {
    // ── ERC-20 storage ──────────────────────────────────────────────

    string public name;
    string public symbol;
    uint8 public constant decimals = 18;

    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    // ── Bridge wiring ───────────────────────────────────────────────

    address public immutable bridge;
    uint256 public immutable peerChainId;
    /// @notice Peer token address on the other chain. ``address(0)`` means
    ///         it has not been initialised yet; ``setPeer`` wires it once.
    address public peerToken;

    /// @notice Deployer / minter / one-shot peer setter.
    address public immutable minter;

    // ── Events ──────────────────────────────────────────────────────

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event BridgeSent(address indexed sender, address indexed recipient, uint256 amount);
    event BridgeMinted(address indexed recipient, uint256 amount);
    event PeerSet(address indexed peerToken);

    // ── Constructor ─────────────────────────────────────────────────

    constructor(
        string memory name_,
        string memory symbol_,
        uint256 initialSupply,
        address bridge_,
        uint256 peerChainId_,
        address peerToken_
    ) {
        require(bridge_ != address(0), "BERC20: bridge=0");
        name = name_;
        symbol = symbol_;
        bridge = bridge_;
        peerChainId = peerChainId_;
        peerToken = peerToken_; // may be address(0); finalise via setPeer
        // The factory is the immediate ``msg.sender`` during a CREATE2
        // deploy from BridgeableERC20Factory; ``tx.origin`` is the user
        // EOA that called the factory and is the natural mint recipient.
        minter = tx.origin;
        if (initialSupply > 0) {
            _mint(tx.origin, initialSupply);
        }
    }

    // ── ERC-20 ──────────────────────────────────────────────────────

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
            require(allowed >= value, "BERC20: insufficient allowance");
            unchecked {
                allowance[from][msg.sender] = allowed - value;
            }
        }
        _transfer(from, to, value);
        return true;
    }

    // ── Mint / burn (test convenience) ──────────────────────────────

    function mint(address to, uint256 amount) external {
        require(msg.sender == minter, "BERC20: not minter");
        _mint(to, amount);
    }

    function burn(address from, uint256 amount) external {
        require(msg.sender == minter, "BERC20: not minter");
        _burn(from, amount);
    }

    // ── Peer wiring ─────────────────────────────────────────────────

    /// @notice One-shot setter for the cross-chain peer address. The peer is
    ///         immutable in spirit; this function only exists to support the
    ///         CREATE2 deploy pattern where the peer address is unknown at
    ///         constructor time on the very first chain.
    function setPeer(address peerToken_) external {
        require(msg.sender == minter, "BERC20: not minter");
        require(peerToken == address(0), "BERC20: peer already set");
        require(peerToken_ != address(0), "BERC20: peer=0");
        peerToken = peerToken_;
        emit PeerSet(peerToken_);
    }

    // ── Cross-chain ─────────────────────────────────────────────────

    /// @notice Burn ``amount`` from the caller and dispatch a bridge message
    ///         that will mint the same amount to ``recipient`` on the peer
    ///         chain.
    function bridgeSend(address recipient, uint256 amount) external {
        require(peerToken != address(0), "BERC20: peer not set");
        require(recipient != address(0), "BERC20: recipient=0");
        require(amount > 0, "BERC20: amount=0");
        _burn(msg.sender, amount);
        bytes memory payload = abi.encodeCall(this.bridgeMint, (recipient, amount));
        IDtnBridge(bridge).send(peerToken, 0, payload);
        emit BridgeSent(msg.sender, recipient, amount);
    }

    /// @notice Mint to ``recipient``. Only callable by the local bridge,
    ///         which is the trusted relay-controlled messenger.
    function bridgeMint(address recipient, uint256 amount) external {
        require(msg.sender == bridge, "BERC20: not bridge");
        _mint(recipient, amount);
        emit BridgeMinted(recipient, amount);
    }

    // ── Internals ───────────────────────────────────────────────────

    function _transfer(address from, address to, uint256 value) internal {
        require(to != address(0), "BERC20: to=0");
        require(balanceOf[from] >= value, "BERC20: insufficient balance");
        unchecked {
            balanceOf[from] -= value;
            balanceOf[to] += value;
        }
        emit Transfer(from, to, value);
    }

    function _mint(address to, uint256 value) internal {
        require(to != address(0), "BERC20: mint to=0");
        totalSupply += value;
        unchecked {
            balanceOf[to] += value;
        }
        emit Transfer(address(0), to, value);
    }

    function _burn(address from, uint256 value) internal {
        require(balanceOf[from] >= value, "BERC20: burn exceeds balance");
        unchecked {
            balanceOf[from] -= value;
        }
        totalSupply -= value;
        emit Transfer(from, address(0), value);
    }
}
