# trader plugin

`RandomTrader` is an actor that coin-flips a swap direction and size each block
and trades against a `SimpleAMM`. It owns an `Actor` (a primitive, not a plugin):
`setup` funds the actor with native balance, moves tokens from the chain
deployer, and approves the AMM; `on_block` chooses a direction and size from the
plugin's deterministic RNG and submits the swap. The same seed produces the same
trade sequence.

`from statelab import RandomTrader`.

## Constructor

```python
RandomTrader(name, amm, token_x, token_y, chain, min_size, max_size, fund_each=0)
```

- `name` - the plugin name; also names the underlying actor.
- `amm` - the `SimpleAMM` plugin to trade against.
- `token_x`, `token_y` - the two tokens (as `Token` plugins).
- `chain` - the chain to trade on.
- `min_size`, `max_size` - inclusive bounds on the per-trade input amount.
- `fund_each` - amount of each token to move from the deployer to the trader and
  approve to the AMM during `setup`. Leave at `0` only if the trader is funded
  elsewhere.

Each block on which `chain` mined, the trader flips a coin for direction
(`X->Y` or `Y->X`), draws a size in `[min_size, max_size]` from `ctx.rng`, and
submits the swap. A successful swap emits a `swap` event; a revert or exception
emits a `swap_error` event and is not retried.

`summary()` reports the count of successful `trades` and `errors`.

## Usage

```python
from statelab import Lab, RandomTrader, SimpleAMM, Time, Token

WAD = 10**18
with Lab(seed=0xC0FFEE, duration=Time(60 * 30), outdir="out/trader") as lab:
    earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
    tx = lab.use(Token("TokenX", "TKX", chain=earth, supply=10**24))
    ty = lab.use(Token("TokenY", "TKY", chain=earth, supply=10**24))
    amm = lab.use(SimpleAMM(earth, tx, ty,
                            initial_liquidity=(1_000 * WAD, 1_000 * WAD)))
    for i in range(5):
        lab.use(RandomTrader(f"Actor{i}", amm=amm, token_x=tx, token_y=ty,
                             chain=earth, min_size=WAD, max_size=50 * WAD,
                             fund_each=1_000 * WAD))
```

Because each trader's RNG is seeded from `(seed, name)`, distinct names give
distinct but reproducible trade streams; reusing a name across runs replays the
same stream.
