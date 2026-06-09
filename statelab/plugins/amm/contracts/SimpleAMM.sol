// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20 {
    function balanceOf(address) external view returns (uint256);
    function transfer(address, uint256) external returns (bool);
    function transferFrom(address, address, uint256) external returns (bool);
}

/// @title SimpleAMM
/// @notice Constant-product AMM (x*y=k) with a 30 bps fee on input.
/// @dev Minimal implementation: no proxies, no external deps, plain storage.
contract SimpleAMM {
    IERC20 public immutable tokenX;
    IERC20 public immutable tokenY;

    uint256 public reserveX;
    uint256 public reserveY;
    uint256 public totalShares;
    mapping(address => uint256) public shares;

    uint256 public constant FEE_BPS = 30;        // 0.30%
    uint256 public constant BPS_DENOM = 10_000;

    event LiquidityAdded(address indexed lp, uint256 dx, uint256 dy, uint256 newShares);
    event LiquidityRemoved(address indexed lp, uint256 dx, uint256 dy, uint256 burnedShares);
    event Swap(address indexed trader, address tokenIn, uint256 amountIn, uint256 amountOut);

    constructor(address _x, address _y) {
        require(_x != address(0) && _y != address(0), "zero addr");
        require(_x != _y, "same token");
        tokenX = IERC20(_x);
        tokenY = IERC20(_y);
    }

    // ---------------------------------------------------------------
    // Liquidity
    // ---------------------------------------------------------------

    function addLiquidity(uint256 dx, uint256 dy) external returns (uint256 newShares) {
        require(dx > 0 && dy > 0, "zero amounts");

        if (totalShares == 0) {
            newShares = _sqrt(dx * dy);
            require(newShares > 0, "shares=0");
        } else {
            // Require dy/dx == reserveY/reserveX, i.e. dy*reserveX == dx*reserveY.
            require(dy * reserveX == dx * reserveY, "ratio");
            // Shares pro-rata to existing reserves (use X side; equivalent under ratio constraint).
            newShares = (dx * totalShares) / reserveX;
            require(newShares > 0, "shares=0");
        }

        require(tokenX.transferFrom(msg.sender, address(this), dx), "tx X");
        require(tokenY.transferFrom(msg.sender, address(this), dy), "tx Y");

        reserveX += dx;
        reserveY += dy;
        totalShares += newShares;
        shares[msg.sender] += newShares;

        emit LiquidityAdded(msg.sender, dx, dy, newShares);
    }

    function removeLiquidity(uint256 burnShares) external returns (uint256 dx, uint256 dy) {
        require(burnShares > 0, "zero shares");
        require(shares[msg.sender] >= burnShares, "insufficient");
        require(totalShares > 0, "no liq");

        dx = (burnShares * reserveX) / totalShares;
        dy = (burnShares * reserveY) / totalShares;
        require(dx > 0 && dy > 0, "zero out");

        shares[msg.sender] -= burnShares;
        totalShares -= burnShares;
        reserveX -= dx;
        reserveY -= dy;

        require(tokenX.transfer(msg.sender, dx), "tx X");
        require(tokenY.transfer(msg.sender, dy), "tx Y");

        emit LiquidityRemoved(msg.sender, dx, dy, burnShares);
    }

    // ---------------------------------------------------------------
    // Swap
    // ---------------------------------------------------------------

    function swapExactIn(address tokenIn, uint256 amountIn, uint256 minOut)
        external
        returns (uint256 amountOut)
    {
        require(amountIn > 0, "zero in");
        require(tokenIn == address(tokenX) || tokenIn == address(tokenY), "bad token");
        require(reserveX > 0 && reserveY > 0, "no liq");

        bool inIsX = (tokenIn == address(tokenX));
        (uint256 rIn, uint256 rOut) = inIsX ? (reserveX, reserveY) : (reserveY, reserveX);

        uint256 amountInWithFee = (amountIn * (BPS_DENOM - FEE_BPS)) / BPS_DENOM;
        amountOut = (rOut * amountInWithFee) / (rIn + amountInWithFee);
        require(amountOut >= minOut, "slippage");
        require(amountOut > 0, "zero out");

        if (inIsX) {
            require(tokenX.transferFrom(msg.sender, address(this), amountIn), "tx in");
            require(tokenY.transfer(msg.sender, amountOut), "tx out");
            reserveX += amountIn;
            reserveY -= amountOut;
        } else {
            require(tokenY.transferFrom(msg.sender, address(this), amountIn), "tx in");
            require(tokenX.transfer(msg.sender, amountOut), "tx out");
            reserveY += amountIn;
            reserveX -= amountOut;
        }

        emit Swap(msg.sender, tokenIn, amountIn, amountOut);
    }

    // ---------------------------------------------------------------
    // Views
    // ---------------------------------------------------------------

    function getReserves() external view returns (uint256, uint256) {
        return (reserveX, reserveY);
    }

    /// @notice Spot price of X in units of Y, WAD-scaled (reserveY * 1e18 / reserveX).
    function getPrice() external view returns (uint256) {
        if (reserveX == 0) return 0;
        return (reserveY * 1e18) / reserveX;
    }

    function quote(address tokenIn, uint256 amountIn) external view returns (uint256) {
        if (amountIn == 0 || reserveX == 0 || reserveY == 0) return 0;
        if (tokenIn != address(tokenX) && tokenIn != address(tokenY)) return 0;

        (uint256 rIn, uint256 rOut) = (tokenIn == address(tokenX))
            ? (reserveX, reserveY)
            : (reserveY, reserveX);

        uint256 amountInWithFee = (amountIn * (BPS_DENOM - FEE_BPS)) / BPS_DENOM;
        return (rOut * amountInWithFee) / (rIn + amountInWithFee);
    }

    function k() external view returns (uint256) {
        return reserveX * reserveY;
    }

    // ---------------------------------------------------------------
    // Internal
    // ---------------------------------------------------------------

    /// @dev Babylonian integer square root.
    function _sqrt(uint256 y) internal pure returns (uint256 z) {
        if (y > 3) {
            z = y;
            uint256 x = y / 2 + 1;
            while (x < z) {
                z = x;
                x = (y / x + x) / 2;
            }
        } else if (y != 0) {
            z = 1;
        }
    }
}
