# `Contract` / `Pair` / `PendingTx`

These three types cover deploying a contract, calling it, and the cross-chain
parity deployment.

## `Contract`

A deployed contract with ABI-driven attribute access. Every ABI function becomes
an attribute: a view or pure function returns the decoded value directly; a
state-changing function submits a transaction and returns a `PendingTx`.

### Deploy

```python
Contract.deploy(chain, artifact, constructor_args=None, contract_name=None,
                from_=None, value=0, gas=6_000_000)
```

- `artifact` - a precompiled artifact dict (`{"abi": ..., "bytecode": ...}`),
  typically from `load_artifact(...)`.
- `constructor_args` - a list of constructor arguments.
- `from_` - the deploying wallet (defaults to `chain.deployer`).

### Calling

```python
value = amm.getPrice()                                  # view: returns the value
pending = amm.swapExactIn(token, amt, 0, from_=alice)   # state-changing: PendingTx
pending.wait()
```

A state-changing call requires `from_=<Wallet>`; calling one without it raises.
Each caller also accepts `value=` and `gas=`.

### Attributes

- `address` - the checksummed address.
- `abi`, `name` - the ABI and a display name.
- `events` - a map from event name to its bound web3 event object.

## `PendingTx`

The handle a state-changing call returns. The transaction is already submitted;
nothing is confirmed until you wait.

- `wait(max_blocks=100, timeout=30.0)` - mine blocks until the tx is included,
  populate `receipt`, decode `return_value`, and return `self`. Raises if it
  never lands.
- `status` - the receipt status (`1` success, `0` revert), or `None` before
  waiting.
- `return_value` - the decoded return value after waiting.
- `events` - the decoded events from the receipt.
- `receipt` - the raw transaction receipt.

## `Pair`

A pair of identically-addressed deployments across chains - the result of a
CREATE2 same-address deploy. Every member shares one `address`.

- `on(chain)` - the `Contract` on a given chain (accepts a `Chain` or a name).
- `on_name(chain_name)` - the `Contract` by chain name.
- `earth` / `mars` - shorthand for the two bundled chains.
- `address` - the shared address.
- iterating a `Pair` yields its per-chain `Contract`s.

```python
pair = lab.create2.deploy_pair("hello", creation_code, abi, "HelloWorld")
assert pair.on(earth).address == pair.on(mars).address
pair.on(earth).getValue()
```
