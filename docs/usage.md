# Running an experiment

An experiment is a `Lab` block: register some chains and plugins, then let it
run. This page walks through the orchestrator, how time and the run loop work,
the files you get out, and how to keep results reproducible.

## The `Lab` context

```python
from statelab import Lab, Time

with Lab(seed=42, duration=Time(60 * 60), outdir="out/run") as lab:
    ...
```

`Lab` is a context manager. Opening it creates the output directory and makes
sure an Anvil node is up. The supported path is a native Anvil you start
yourself, with `auto_docker=False`; if you leave `auto_docker=True`, StateLab
brings up the bundled Docker pair only when the ports are not already live (see
[Anvil: native or Docker](../README.md#anvil-native-or-docker)). Closing it runs
the experiment, if you did not call `run()` yourself, and writes the output
files.

The parameters you will actually reach for are `seed`, `duration`, and `outdir`.
The rest have defaults worth leaving alone until you need them.

| Parameter     | Default            | What it does                                            |
|---------------|--------------------|---------------------------------------------------------|
| `seed`        | `0`                | Seeds every plugin's RNG and fixes the whole run.       |
| `duration`    | `Time(60)`         | How long to run, in base units (a plain `int` works).   |
| `outdir`      | `"out/lab"`        | Where the three output files land.                      |
| `base`        | `"1s"`             | The base time unit: `"1s"`, `"1m"`, or integer seconds. |
| `fastforward` | `1`                | Default multiplier for the clock's fast-forward.        |
| `mnemonic`    | Anvil dev mnemonic | The HD mnemonic every wallet derives from.              |
| `wall_origin` | `1_700_000_000`    | Unix-seconds origin written onto block timestamps.      |
| `auto_docker` | `True`             | Bring up the bundled Docker Anvil pair if the ports are not already live. `False` for a native Anvil. |
| `anvil_ports` | `[8545, 8546]`     | The Anvil ports this run targets; a disjoint pair lets runs share a machine. |

## How time works

StateLab runs on a simulated clock, not the wall clock.
Each chain has a block interval, the `Lab` keeps one clock for all of them, and
the run loop does this: jump the clock to the next chain that is due to mine,
mine it, call every plugin's `on_block`, and repeat, until the clock reaches
`duration`.

Two things follow. First, nothing waits in real time. A run that covers an hour
of chain activity finishes in milliseconds, and a 30-day `duration` costs the
same as a 30-second one. Second, "a block every 12 seconds" is a statement about
*simulated* time: `blocktime=Time(12)` mines every twelve simulated seconds,
`Time(60)` every minute. Two chains with different block times advance on their
own schedules under the one clock, so a single tick may mine both, one, or
neither.

When you would rather step time by hand than let the loop drive it, say to set up
a precise scenario, `chain.mine()` mines a block now and `chain.head_number()`
tells you where you are.

## Registering chains

```python
earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
mars  = lab.chain("mars",  chain_id=31338, blocktime=Time(12))
```

`lab.chain(name, chain_id, blocktime)` connects to an Anvil node, checks its
chain id matches what you passed, resets it to a clean state, and returns a
`Chain`. The names `earth` and `mars` default to ports 8545 and 8546; for a
third chain, point it at a node with `rpc_url=`. The `Chain` you get back is
what you wire plugins to.

## Registering plugins

```python
tx  = lab.use(Token("TokenX", "TKX", chain=earth, supply=10**24))
amm = lab.use(SimpleAMM(earth, tx, ty, initial_liquidity=(a, b)))
lab.use(Monitor("price", chain=earth, call=amm.get_price))
```

`lab.use(plugin)` registers a plugin and hands the same instance back, so it
reads naturally in an assignment and a later plugin can take an earlier one as a
dependency, as the AMM above is handed its two tokens. Each plugin needs a unique
`name`; register two with the same name and it raises. Registration order is the
order of `setup` and of every per-block step, which makes it part of the
determinism contract. Keep it stable across runs you mean to compare.

## The lifecycle

A run has three phases.

1. **Setup.** `Lab` calls each plugin's `setup(lab)` in registration order.
   Plugins deploy contracts, wire cross-chain peers, and fund wallets here.
   Setting up bridges and CREATE2 contracts before any chain-specific
   transactions keeps the deployer nonces equal across chains, which is what
   lets a contract land at the same address everywhere.
2. **Run loop.** The clock advances block by block. Each tick mines every chain
   whose block time is due, then calls `on_block(ctx)` on every plugin in
   registration order with a fresh `Context`. It stops when the clock reaches
   `duration`.
3. **Output.** `Lab` gathers everything recorded through `ctx`, asks each plugin
   for its `summary()`, and writes the three files.

If a plugin throws inside `on_block`, the run does not die. `Lab` logs a
`plugin_error` event and carries on, so when a run comes out wrong, `events.csv`
is the first place to look.

## The output files

Three files land in `outdir`:

- **`events.csv`** - the per-block log. Every mined block gets a `block` row per
  chain; plugins add their own rows through `ctx.emit(...)` (the trader's `swap`
  rows, the bridge's `bridge_deliver` rows). Columns depend on what was emitted;
  the common ones are `t` (simulated time), `kind`, and `who`.
- **`monitors.csv`** - monitor samples written with
  `ctx.record(name, value, chain=...)`. Columns: `name`, `t`, `block`, `value`,
  `chain`.
- **`summary.json`** - the run config (`seed`, `duration`, `chains`, `plugins`),
  any errors, and a `plugin_summaries` map keyed by plugin name for every plugin
  that returned a summary.

## Reproducibility

A run is pinned by its `seed` and the registration order of its chains and
plugins. Hold those fixed and the three files come out byte-for-byte identical,
run to run and machine to machine. That holds because the clock advances by
computed deltas rather than wall time, plugins step in a fixed order, and each
plugin draws from its own `(seed, name)` RNG instead of a shared global one. So
to compare two configurations, change only the thing under study and leave the
seed and the registration order alone.
