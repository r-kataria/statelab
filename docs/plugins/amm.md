# amm plugin

`SimpleAMM` is a single-chain constant-product (`x * y = k`) automated market
maker over two tokens, with a 30 bps fee on the input. Its `setup` deploys the
AMM bound to the two tokens and optionally seeds initial liquidity from the chain
deployer (who holds the token supply).

`from statelab import SimpleAMM`.

## Constructor

```python
SimpleAMM(chain, token_x, token_y, initial_liquidity=None, plugin_name="amm")
```

- `chain` - the chain to deploy on.
- `token_x`, `token_y` - the two tokens. Each may be a `Token` plugin, an
  `ERC20` helper, or anything exposing `.address` and `.contract`.
- `initial_liquidity` - an optional `(dx, dy)` tuple. When given, `setup`
  approves the AMM from the deployer and seeds those reserves.
- `plugin_name` - the plugin name (defaults to `"amm"`).

## Key methods

- `get_price()` - spot price of X in units of Y, WAD-scaled
  (`reserveY * 1e18 / reserveX`).
- `get_reserves()` - the `(reserveX, reserveY)` pair as integers.
- `swap(actor, token_in, amount_in, min_out=0)` - submit a `swapExactIn` signed
  by `actor`; returns a `PendingTx`. `token_in` may be a token object or an
  address.

`summary()` reports the final `price`, `reserveX`, and `reserveY`.

## Usage

```python
from statelab import Lab, Monitor, SimpleAMM, Time, Token

WAD = 10**18
with Lab(seed=1, duration=Time(60 * 30), outdir="out/amm") as lab:
    earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
    tx = lab.use(Token("TokenX", "TKX", chain=earth, supply=10**24))
    ty = lab.use(Token("TokenY", "TKY", chain=earth, supply=10**24))
    amm = lab.use(SimpleAMM(earth, tx, ty,
                            initial_liquidity=(1_000 * WAD, 1_000 * WAD)))
    lab.use(Monitor("price", chain=earth, call=amm.get_price))
```

`get_price` is a plain callable, which makes it a natural argument to a
`Monitor` that samples the price once per block.
