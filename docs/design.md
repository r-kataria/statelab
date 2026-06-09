# Architecture

StateLab keeps a small, domain-agnostic core and pushes everything else into
plugins. Three layers, bottom to top: the core orchestrator and clock, the
primitives plugins are built from, and the plugins themselves.

## Three layers

### Core (`statelab.core`)

The non-removable part.

- **`Lab`** owns the chain registry, the plugin registry, the clock, the
  block-granular run loop, and the output writers. It connects to a native
  Anvil you started, or optionally brings up the bundled Docker pair. It is the
  only object an experiment script talks to directly.
- **`TimeControl`** is the authoritative simulated clock; `TimeValue` is an
  immutable duration in base units; `Distribution` is a pluggable interval
  sampler. `Time` (a module-level `TimeControl`) is the convenience constructor:
  `Time(12)` returns `TimeValue(12)`.

### Primitives (also in `statelab.core`)

The vocabulary plugins are built from, low-level and domain-agnostic:

- **`Chain`** - an Anvil JSON-RPC wrapper with manual block control.
- **`Wallet`** - an EOA derived deterministically from the dev mnemonic.
- **`Contract` / `PendingTx` / `Pair`** - deploy a precompiled artifact and wrap
  it with ABI-driven attribute access; `PendingTx` is the handle a
  state-changing call returns; `Pair` is one deployment present at an identical
  address on several chains.
- **`Actor`** - a funded wallet present at the same address on one or more
  chains, with a transaction helper. An actor is a primitive, not a plugin.
- **`Plugin` / `Context`** - the plugin base class and the per-block context.
- **CREATE2 same-address deploy** - the factory contract plus the address-parity
  logic, reached through `lab.create2`. It is a core primitive rather than a
  plugin because several plugins need it.

### Plugins (`statelab.plugins`)

Everything with domain behaviour. A plugin is a set of Solidity contracts, their
shipped compiled artifacts, Python bindings, and behaviour, self-contained in
one directory that carries its own `contracts/` and `artifacts/`. The bundled
plugins are token, bridge, AMM, monitor, and trader.

## The `Plugin` protocol and `Context`

```python
class Plugin:
    name: str
    def setup(self, lab) -> None: ...          # deploy, wire, fund
    def on_block(self, ctx) -> None: ...        # optional per-block behaviour
    def summary(self) -> dict | None: ...       # optional summary.json section
```

All three hooks are optional; the base class no-ops them and returns `None` from
`summary()`. The only required attribute is `name`, which must be unique within
a run and which keys both the plugin's RNG and its summary section.

`Context` is constructed fresh for each plugin on each block tick and carries:

- `now` - the current simulated time in base units.
- `blocks` - a map from chain name to its current head block number.
- `mined` - the list of chain names that mined on this tick. A plugin that acts
  per block (a monitor, a trader) checks whether its chain is in `mined` before
  acting.
- `rng` - a `random.Random` seeded from `(lab.seed, plugin.name)`, so each
  plugin's randomness is independent and reproducible.
- `lab` - the orchestrator, for plugins that need to reach chains or other state.
- `record(name, value, chain=None)` - append a monitor sample.
- `emit(event)` - append an event row (a dict; `t` is added automatically).

`record` and `emit` are the single output path: everything that ends up in
`monitors.csv` and `events.csv` flows through the context.

## The block-granular run loop

On `run()`, `Lab` first calls `setup(lab)` on every plugin in registration
order. It then advances the clock to the next due event, the earliest of any
chain's next block time and the run's end. On reaching that time it mines every
chain whose block time has elapsed, emits a `block` event for each, and calls
`on_block(ctx)` on every plugin in registration order. This repeats until
simulated time reaches `duration`.

Because chains have independent block times, a tick may mine several chains at
once, one, or none; `ctx.mined` tells each plugin which fired. A plugin's
`on_block` exception is caught and recorded as a `plugin_error` event so a single
misbehaving plugin cannot abort the whole run.

## CREATE2 address parity

Cross-chain designs frequently need a contract to live at the *same* address on
every chain. A bridgeable token, for example, references its peer by address. A
plain deployment cannot guarantee this, because the address depends on the
deployer and its nonce. StateLab provides same-address deployment through
`lab.create2`: a shared factory deploys arbitrary creation code via the EVM's
CREATE2 opcode, whose resulting address depends only on the factory address, a
salt, and the creation code, not on the deployer's nonce.

Two invariants make this work, and the framework enforces both. First, the
factory itself must land at the same address on every chain, which holds only
when the deployers' nonces are equal at deploy time; `create2` checks the nonces
match and otherwise refuses. This is why bridges and tokens are set up before any
asymmetric per-chain transactions. Second, the creation code must be
byte-identical across chains, which constrains constructor arguments: the
`BridgeableToken` plugin holds the peer fields at zero in the constructor and
wires the real peer afterwards, keeping the bytes identical so the address
matches. The result is a `Pair`, one logical contract reachable as `pair.on(chain)`
with a single shared `address`.

## Deterministic batched setup

Determinism is why StateLab has no threads and no
shared global RNG. Three rules hold it together: plugins step in registration
order on every block; setup submits transactions in registration order per
chain; and each plugin draws from its own RNG seeded from `(seed, name)`. The
clock advances by computed deltas rather than wall time, and the output writers
serialise rows in append order. Put together, that makes the three output files
byte-for-byte identical across runs and machines for a fixed seed and
registration order.
