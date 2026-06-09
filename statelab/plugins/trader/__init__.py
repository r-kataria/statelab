"""RandomTrader plugin: an actor that coin-flips a swap direction each block.

Owns an Actor (Actor is a primitive, not a Plugin). `setup` funds native, moves
tokens from the chain deployer, and approves the AMM. `on_block` uses the
deterministic per-plugin ctx.rng to choose direction + size and swap. Same seed
=> identical trade sequence.
"""
from __future__ import annotations

from ...core.actor import Actor
from ...core.plugin import Plugin


class RandomTrader(Plugin):
    def __init__(self, name, amm, token_x, token_y, chain,
                 min_size, max_size, fund_each=0):
        self.name = name
        self.amm = amm
        self.token_x = token_x
        self.token_y = token_y
        self.chain = chain
        self.min_size = int(min_size)
        self.max_size = int(max_size)
        self.fund_each = int(fund_each)
        self.actor = None
        self.trades = 0
        self.errors = 0

    def setup(self, lab) -> None:
        self.actor = Actor(name=self.name, chains=[self.chain])
        self.actor.fund(native=10**18, chain=self.chain)
        if self.fund_each > 0:
            wallet = self.actor.wallet_on(self.chain)
            for token in (self.token_x, self.token_y):
                token.contract.transfer(
                    self.actor.address, self.fund_each, from_=self.chain.deployer).wait()
                token.approve(wallet, self.amm.contract.address, 2**256 - 1)

    def on_block(self, ctx) -> None:
        if self.chain.name not in ctx.mined:
            return
        heads = bool(ctx.rng.randint(0, 1))
        size = ctx.rng.randint(self.min_size, self.max_size)
        token_in = self.token_x if heads else self.token_y
        direction = "X->Y" if heads else "Y->X"
        try:
            tx = self.amm.swap(self.actor, token_in, size, 0).wait()
        except Exception as exc:
            self.errors += 1
            ctx.emit({"kind": "swap_error", "who": self.name, "dir": direction,
                      "error": repr(exc)})
            return
        if tx.status == 1:
            self.trades += 1
            ctx.emit({"kind": "swap", "who": self.name, "dir": direction, "amount_in": size})
        else:
            self.errors += 1
            ctx.emit({"kind": "swap_error", "who": self.name, "dir": direction,
                      "error": "reverted"})

    def summary(self) -> dict:
        return {"trades": self.trades, "errors": self.errors}
