# monitor plugin

`Monitor` samples a callable once per block and records the result through the
per-block context, so the sampled series ends up in `monitors.csv`. It deploys
no contracts.

`from statelab import Monitor`.

## Constructor

```python
Monitor(name, chain, call, every="block")
```

- `name` - the sample name; becomes the `name` column in `monitors.csv` and must
  be unique among registered plugins.
- `chain` - the chain whose block cadence drives the sampling.
- `call` - a zero-argument callable returning the value to record. Any exception
  it raises is captured and recorded as the value rather than aborting the run.
- `every` - `"block"` (record only on ticks where `chain` mined, the default) or
  `"tick"` (record on every `on_block` call).

Each recorded row carries `name`, the simulated time `t`, the chain's `block`
number, the `value`, and the `chain` name.

## Usage

```python
from statelab import Lab, Monitor, SimpleAMM, Time, Token

WAD = 10**18
with Lab(seed=1, duration=Time(60 * 30), outdir="out/mon") as lab:
    earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
    tx = lab.use(Token("TokenX", "TKX", chain=earth, supply=10**24))
    ty = lab.use(Token("TokenY", "TKY", chain=earth, supply=10**24))
    amm = lab.use(SimpleAMM(earth, tx, ty,
                            initial_liquidity=(1_000 * WAD, 1_000 * WAD)))
    lab.use(Monitor("price", chain=earth, call=amm.get_price))
```

`call` is any callable, so a monitor can sample a plugin accessor (`amm.get_price`),
a bound contract view, or a small lambda such as
`lambda: token.balance_of(alice, earth)`.
