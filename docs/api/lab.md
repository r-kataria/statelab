# `Lab`

The orchestrator. It owns the chain registry, the plugin registry, the clock,
the block-granular run loop, and the output writers. Use it as a context
manager.

## Constructor

```python
Lab(seed=0, duration=Time(60), outdir="out/lab", base="1s", fastforward=1,
    mnemonic=<dev mnemonic>, wall_origin=1_700_000_000, auto_docker=True,
    anvil_ports=[8545, 8546])
```

- `seed` - seeds every plugin's RNG; fixes the run.
- `duration` - run length in base units; a `TimeValue` or an `int`.
- `outdir` - directory for the output files.
- `base` - base time unit (`"1s"`, `"1m"`, or an integer of seconds).
- `fastforward` - default multiplier for the clock's `fastforward`.
- `mnemonic` - HD mnemonic that derives every wallet.
- `wall_origin` - unix-seconds origin projected onto chain block timestamps.
- `auto_docker` - bring up the bundled Docker Anvil pair if the ports are not
  already live. Pass `False` to run against a native Anvil you started yourself
  (the supported path; see the [README](../../README.md#anvil-native-or-docker)).
- `anvil_ports` - the ports this run targets; a disjoint pair lets several runs
  share one machine.

## Context-manager behaviour

- **Enter** creates `outdir` and, if `auto_docker`, brings up the bundled Docker
  Anvil pair unless `anvil_ports` are already live.
- **Exit** runs the experiment if `run()` was not called and no exception is in
  flight, then writes the output files. An exception in the block is recorded in
  the summary's `errors` and re-raised by the interpreter; the outputs are still
  written.

## Attributes and methods

- `chain(name, chain_id, blocktime, rpc_url=None)` - connect to a node, verify
  its chain id, reset it, and return a `Chain`. `blocktime` must be positive.
- `use(plugin)` - register a plugin and return it. Names must be unique.
- `run()` - run setup then the loop, then write output. Idempotent.
- `create2` - a lazily built CREATE2 deployer over the registered chains
  (see [create2](create2.md)).
- `Time` - the lab's own `TimeControl`, bound to `base`/`fastforward`/`wall_origin`.
- `chains` / `plugins` - the registered chains and plugins, in registration order.
- `seed`, `duration`, `outdir` - as constructed.

## Output

On write, `Lab` produces `events.csv`, `monitors.csv`, and `summary.json` in
`outdir`. The summary holds `seed`, `duration`, the chain and plugin names, any
`errors`, and a `plugin_summaries` map for plugins that returned a `summary()`.

```python
from statelab import Lab, Time

with Lab(seed=42, duration=Time(60 * 60), outdir="out/run") as lab:
    earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
    # lab.use(...) plugins here; lab.run() runs on exit.
```
