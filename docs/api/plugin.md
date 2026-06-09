# `Plugin` / `Context`

The plugin protocol and the per-block context. To author a plugin end to end,
see [../writing-a-plugin.md](../writing-a-plugin.md); this page is the reference.

## `Plugin`

The base class. Subclasses override the hooks they need; all three are optional
and the base no-ops them.

```python
class Plugin:
    name: str
    def setup(self, lab) -> None: ...        # deploy contracts, wire peers, fund
    def on_block(self, ctx) -> None: ...      # optional per-block behaviour
    def summary(self) -> dict | None: ...     # optional summary.json section
```

- `name` - the only required attribute. It must be unique within a run, keys the
  plugin's RNG, and names its summary section.
- `setup(lab)` - runs once at the start of `run()`, in registration order.
- `on_block(ctx)` - runs once per block tick, in registration order. An
  exception here is recorded as a `plugin_error` event rather than aborting the
  run.
- `summary()` - returns a dict merged into `summary.json` under the plugin name,
  or `None`.

## `Context`

Constructed fresh for each plugin on each tick and handed to `on_block`.

- `now` - current simulated time in base units.
- `blocks` - map from chain name to its current head block number.
- `mined` - list of chain names that mined this tick. A monitor or trader checks
  whether its chain is in `mined` before acting.
- `rng` - a `random.Random` seeded from `(lab.seed, plugin.name)`.
- `lab` - the orchestrator, for reaching chains or other state.
- `record(name, value, chain=None)` - append a monitor sample (a row in
  `monitors.csv`).
- `emit(event)` - append an event row (`event` is a dict; `t` is added
  automatically) to `events.csv`.

## `make_plugin_rng`

```python
make_plugin_rng(seed, name) -> random.Random
```

Builds the deterministic per-plugin RNG from `(seed, name)`. `Lab` calls this to
seed each plugin's `ctx.rng`; it is exported for tests and for plugins that need
an extra named stream.
