# bridge plugin

`RelayBridge` is a bidirectional cross-chain bridge between two chains, with a
Python-side relay. A `DtnBridge` contract is deployed on each side. The contract
recognises a single payload, a low-level call `(target, value, data)` to be
executed on the destination chain. Tokens are not escrowed by the bridge. Movement
is performed by the token contracts themselves.

`from statelab import RelayBridge, PendingBridgeTx`.

## Message lifecycle

1. **Send.** A caller invokes `send_call` (or `send_raw`), which runs
   `DtnBridge.send` on the source chain and emits a `MessageSent` log.
2. **Queue.** The relay picks the message up - eagerly on send, or lazily via
   `poll()` - and stamps it with `deliver_at = now + delay`.
3. **Deliver.** Once simulated time passes `deliver_at`, the relay submits
   `DtnBridge.deliver(...)` on the destination chain. An on-chain `delivered`
   mapping makes repeated attempts idempotent.

As a plugin, `setup` deploys the `DtnBridge` pair and binds the clock, and
`on_block` runs `poll()` then delivers any due messages once per tick.

## Constructor

```python
RelayBridge(chain_a, chain_b, delay, n_relays=1, relay_drop_rate=0.0,
            relay_seed=0, name="bridge")
```

- `chain_a`, `chain_b` - the two endpoints.
- `delay` - the per-message relay delay, a `TimeValue`.
- `n_relays` - number of independent relays that attempt each message (`>= 1`).
- `relay_drop_rate` - probability in `[0, 1]` that a given relay drops a given
  message. Drops are deterministic per `(src_nonce, relay_idx)`, so a
  configuration always produces the same pattern.
- `relay_seed` - seeds the drop decisions.
- `name` - the plugin name.

## Key methods

- `send_call(target_contract, method_name, args, *, src=None, dst=None, from_, value=0)`
  queue a cross-chain contract call; the target must already live on `dst`.
- `send_raw(*, target_address, data, value=0, src=None, dst=None, from_)`
  low-level send when you already have raw calldata.
- `poll()` - scan both sides for new `MessageSent` logs and enqueue them.
- `deliver_due(now)` - deliver every queued message whose delay has elapsed;
  returns the count delivered this pass.
- `force_deliver(src_nonce, src_chain_name=None, from_=None)` - submit a queued
  message unconditionally, bypassing relay drops (the "owner submits the proof
  themselves" escape hatch).
- `pending()` - messages not yet delivered.
- `address_on(chain)` / `bridge_on(chain)` - the bridge address / `Contract` on
  a chain.

`summary()` reports `pending`, `delivered`, and `failed` counts.

## `PendingBridgeTx`

The handle returned by `send_call`, `send_raw`, and `BridgeableToken.bridge_token`.
The source-side send is already mined when the handle is returned; the
destination-side delivery happens later in simulated time.

- `delivered` - whether the message has landed on the destination chain.
- `deliver_at` - the simulated time at which delivery becomes due.
- `wait_source()` - ensure the source-side tx is included (kept for symmetry).
- `wait_delivery(timeout_blocks=10_000)` - drive the simulated clock forward
  until the message lands. Runs in simulated time; raises if the clock is
  missing or frozen.

## Usage

```python
from statelab import Lab, RelayBridge, Time

with Lab(seed=7, duration=Time(60 * 60), outdir="out/bridge") as lab:
    earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
    mars  = lab.chain("mars",  chain_id=31338, blocktime=Time(12))
    bridge = lab.use(RelayBridge(earth, mars, delay=Time(24)))
    # A redundant, lossy relay: three relays, each dropping 20% of messages.
    # bridge = lab.use(RelayBridge(earth, mars, delay=Time(24),
    #                              n_relays=3, relay_drop_rate=0.2))
```

Register the bridge before any asymmetric per-chain transactions; the `DtnBridge`
pair must land at the same address on both chains, which holds only when the
deployer nonces match at deploy time.
