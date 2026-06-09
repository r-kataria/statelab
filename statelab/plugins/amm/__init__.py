"""SimpleAMM plugin: a single-chain constant-product (x*y=k) AMM.

`setup` deploys the AMM bound to two tokens and optionally seeds liquidity from
the chain deployer (who holds the token supply). The baseline AMM that
lane-options is compared against.
"""
from __future__ import annotations

from typing import Any, Optional

from web3 import Web3

from ...core.build import load_artifact
from ...core.contract import Contract
from ...core.plugin import Plugin


def _addr(token: Any) -> str:
    return token.address if hasattr(token, "address") else token


def _contract_of(token: Any):
    return token.contract if hasattr(token, "contract") else token


class SimpleAMM(Plugin):
    def __init__(self, chain, token_x, token_y,
                 initial_liquidity: Optional[tuple] = None, plugin_name: str = "amm"):
        self.name = plugin_name
        self.chain = chain
        self.token_x = token_x
        self.token_y = token_y
        self.initial_liquidity = initial_liquidity
        self.contract = None

    def setup(self, lab) -> None:
        art = load_artifact(package="statelab.plugins.amm",
                            sol_file="SimpleAMM.sol", contract_name="SimpleAMM")
        self.contract = Contract.deploy(
            self.chain, art,
            constructor_args=[Web3.to_checksum_address(_addr(self.token_x)),
                              Web3.to_checksum_address(_addr(self.token_y))],
            contract_name="SimpleAMM", from_=self.chain.deployer,
        )
        if self.initial_liquidity is not None:
            self._seed_liquidity(*self.initial_liquidity)

    def _seed_liquidity(self, dx: int, dy: int) -> None:
        dep = self.chain.deployer
        for token in (self.token_x, self.token_y):
            _contract_of(token).approve(
                self.contract.address, 2**256 - 1, from_=dep).wait()
        tx = self.contract.addLiquidity(int(dx), int(dy), from_=dep)
        tx.wait()
        if tx.status != 1:
            raise RuntimeError(f"SimpleAMM.setup: addLiquidity failed: {tx.receipt}")

    def get_price(self) -> int:
        return int(self.contract.getPrice())

    def get_reserves(self):
        rx, ry = self.contract.getReserves()
        return int(rx), int(ry)

    def swap(self, actor, token_in, amount_in, min_out: int = 0):
        """Submit a swapExactIn signed by `actor`. Returns a PendingTx."""
        return actor.call(self.contract, "swapExactIn",
                          Web3.to_checksum_address(_addr(token_in)),
                          int(amount_in), int(min_out), chain=self.chain)

    def summary(self) -> dict:
        rx, ry = self.get_reserves()
        return {"price": self.get_price(), "reserveX": int(rx), "reserveY": int(ry)}
