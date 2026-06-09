# StateLab

A programmable, multi-chain EVM simulator. StateLab runs real
[Anvil](https://book.getfoundry.sh/anvil/) chains and deploys real Solidity, but
hands you the clock and lets you build the world from Python. Mine blocks on
demand, run several chains side by side, give a bridge whatever latency you
want, and replay a whole run bit-for-bit from a seed.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)

It sits between a unit-test harness and a full devnet. Foundry and Hardhat test
one chain against the wall clock; a production fork gives you a chain but not a
clock you can steer or an easy way to wire several together. StateLab is for the
ground in between: cross-chain protocols, time-dependent mechanisms, latency and
MEV scenarios, and long simulations you need to reproduce exactly.

## What it gives you

- **A clock you own.** Time moves only when you move it. A run advances
  simulated time, mines each chain's due blocks, and steps your code once per
  block. Thirty minutes of chain time takes milliseconds of wall time, with no
  real waiting and no `sleep`.
- **Many chains at once.** Declare as many chains as you need, each with its own
  id and block time, and connect them with a relay whose delivery delay you set
  in simulated seconds.
- **Real EVM, real Solidity.** Contracts run as compiled bytecode on genuine
  Anvil nodes. You exercise the actual contract, not a Python reimplementation
  of it.
- **Deterministic by construction.** The same seed produces byte-identical
  output, so a change in a result is attributable to your change and not to
  noise.
- **Composable plugins.** Tokens, AMMs, bridges, monitors, and traders are
  plugins over a small core. Write your own, or ship one as a separate pip
  package; the core never needs editing.

## Install

Prerequisites: Python 3.10+ and [Foundry](https://book.getfoundry.sh/) (for its
`anvil` binary).

```bash
git clone https://github.com/r-kataria/statelab
cd statelab
pip install -e .
```

This pulls in `web3`, `eth-account`, and `pandas`. Contracts ship as
precompiled artifacts, so `forge` is only needed to rebuild them, never at
runtime.

## Anvil: native or Docker

StateLab drives Anvil over JSON-RPC with auto-mining off: it mines every block
itself, on the simulated clock. The supported path is a native Anvil you start
yourself. Docker is an option if you would rather not install Foundry.

- **Native (the supported path).** Start the nodes once and leave them running:

  ```bash
  anvil --no-mining --chain-id 31337 --port 8545 &   # earth
  anvil --no-mining --chain-id 31338 --port 8546 &   # mars
  ```

  Then point a `Lab` at them with `auto_docker=False`. The default ports are
  8545 (earth) and 8546 (mars); `anvil_ports=[...]` targets a different pair, so
  several runs can share one machine on disjoint ports. A third chain takes an
  explicit `rpc_url=` on `lab.chain(...)`.

  ```python
  with Lab(seed=0, duration=Time(60), outdir="out/run", auto_docker=False) as lab:
      earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
      mars  = lab.chain("mars",  chain_id=31338, blocktime=Time(12))
  ```

- **Docker (optional).** With `auto_docker=True` (the default), StateLab brings
  up the bundled `docker compose` Anvil pair if the ports are not already live,
  and leaves them up for the next run. This needs Docker but not Foundry.
  StateLab checks the ports first either way, so an Anvil you already started is
  always used as-is.

## Quickstart

A single-chain market: two ERC-20 tokens, a constant-product AMM seeded with
liquidity, a price monitor, and five coin-flipping traders. Leaving the `with`
block runs the experiment and writes the output files.

```python
from statelab import Lab, Monitor, RandomTrader, SimpleAMM, Time, Token

WAD = 10**18

with Lab(seed=0xC0FFEE, duration=Time(60 * 30), outdir="out/coinflip") as lab:
    earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))

    tx = lab.use(Token("TokenX", "TKX", chain=earth, supply=10**24))
    ty = lab.use(Token("TokenY", "TKY", chain=earth, supply=10**24))

    amm = lab.use(SimpleAMM(earth, tx, ty,
                            initial_liquidity=(1_000 * WAD, 1_000 * WAD)))

    lab.use(Monitor("price", chain=earth, call=amm.get_price))

    for i in range(5):
        lab.use(RandomTrader(f"Actor{i}", amm=amm, token_x=tx, token_y=ty,
                             chain=earth, min_size=WAD, max_size=50 * WAD,
                             fund_each=1_000 * WAD))
```

`duration=Time(60 * 30)` is thirty minutes of simulated time, mined twelve
seconds at a time. The run finishes near-instantly and leaves three files in
`out/coinflip/`: `monitors.csv` (the price series), `events.csv` (the per-block
log of blocks and swaps), and `summary.json` (the run config and each plugin's
final state).

## More than one chain

Two chains and a relay between them. A `BridgeableToken` lives at the same
address on both, and moves burn-on-source / mint-on-destination through the
relay.

```python
from statelab import BridgeableToken, Lab, RelayBridge, Time

WAD = 10**18

with Lab(seed=1, duration=Time(60 * 10), outdir="out/bridge") as lab:
    earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
    mars  = lab.chain("mars",  chain_id=31338, blocktime=Time(12))

    bridge = lab.use(RelayBridge(earth, mars, delay=Time(24)))

    usdc = lab.use(BridgeableToken("USD Coin", "USDC", bridge=bridge,
                                   supply_per_chain=1_000_000 * WAD))
```

A transfer sent on `earth` is delivered on `mars` one `delay` later, in
simulated time, so the delay is exact and the run does not wait it out in wall
time. Change that one number to model a fast L2 bridge or a 24-minute
interplanetary link. The relay carries arbitrary calls too, which is how a
contract on one chain triggers one on another. See
`tests/test_token_bridge.py` for the full driven transfer.

## The clock

On a real chain, time happens to you: a block lands every few seconds whether you
are ready or not, and "wait a day" means waiting a day. In StateLab, time is a
value you advance. The `Lab` holds one simulated clock, each chain has a block
interval, and the run loop jumps the clock to the next due block, mines it, runs
your code, and repeats. Wall seconds never enter into it.

That covers cases that are awkward or impossible otherwise:

- **Time-dependent logic, tested instantly.** Vesting cliffs, TWAP windows,
  auction deadlines, option expiry, funding accrual, and timelocks: anything
  gated on elapsed time. A 30-day cliff is `Time(30 * 86400)`, and the run still
  finishes in milliseconds. No cheatcode bookkeeping, no real waiting.
- **Cross-chain latency as a dial.** A relay delivers its message `delay` later,
  in simulated time. Model a 2-second rollup bridge or a 24-minute interplanetary
  link by changing one number, and watch what a contract does while the message
  is still in flight.
- **Reproducible runs.** The clock moves by exact deltas, so a run is
  byte-identical every time. You can sweep thousands of seeds in the wall time a
  real-clock harness spends on one, and a regression is your change rather than
  timing jitter.
- **Block-by-block control.** Plugins run once per block and see exactly which
  chains mined. When you would rather script a sequence by hand, `chain.mine()`
  and `chain.head_number()` are right there.

If your system lives on one chain and ignores time, a normal test framework is
simpler and you should use one. StateLab is for the case where time or a second
chain starts to matter.

## The plugin model

A plugin bundles Solidity contracts, their shipped compiled artifacts, Python
bindings, and behaviour. It subclasses `Plugin` and implements two optional
hooks:

- `setup(lab)`: deploy contracts, wire peers, fund wallets. Runs once at the
  start, in the order plugins were registered.
- `on_block(ctx)`: per-block behaviour. The `Context` carries the current
  simulated time, the chains that mined this tick, a plugin-scoped deterministic
  RNG, and `ctx.record(...)` / `ctx.emit(...)` to feed the output files.

A plugin can also implement `summary()` to add a section to `summary.json`.
Plugins receive their dependencies by being handed other plugins: `SimpleAMM`
takes its two `Token`s, a `BridgeableToken` takes its `RelayBridge`. There is no
declarative dependency graph and no auto-discovery. A third party ships a
plugin as a separate pip package that imports `statelab` and subclasses
`Plugin`. The quickest start is to copy
[`examples/plugin-template/`](examples/plugin-template/), a working plugin you
rename and fill in. The full walk-through is in
[docs/writing-a-plugin.md](docs/writing-a-plugin.md).

## Determinism

Same `seed`, byte-identical `events.csv`, `monitors.csv`, and `summary.json`.
The guarantee rests on three rules:

- plugins are stepped in registration order, every block;
- setup submits transactions in registration order, per chain;
- each plugin gets its own RNG seeded from `(seed, plugin.name)`.

## Documentation

- [docs/usage.md](docs/usage.md): running an experiment, the lifecycle, the output files.
- [docs/design.md](docs/design.md): the core layers, the plugin protocol, the run loop, CREATE2 address parity.
- [docs/writing-a-plugin.md](docs/writing-a-plugin.md): authoring a plugin and shipping one as its own package.
- [docs/plugins/](docs/plugins/): the bundled plugins: token, bridge, AMM, monitor, trader.
- [docs/api/](docs/api/): reference for the core primitives.

The `tests/` directory doubles as worked usage: `test_coinflip.py`,
`test_token_bridge.py`, and `test_create2.py` each set up and run a small world
end to end.

## License

MIT. See [LICENSE](LICENSE).
