# `create2`

Same-address cross-chain deployment. CREATE2 derives a contract's address from
the factory address, a salt, and the creation code - not from the deployer's
nonce - so the same creation code at the same salt lands at the same address on
every chain. StateLab exposes this as `lab.create2`, a `Create2Deployer` built
lazily over the registered chains. Several plugins (notably `BridgeableToken`)
use it; you reach it the same way for your own.

## `lab.create2`

A `Create2Deployer` over `lab.chains`, built on first access.

```python
lab.create2.deploy_pair(name, creation_code, abi, contract_name, salt=None)
```

- `name` - a label for the resulting `Pair`; also the default salt source.
- `creation_code` - the deploy bytecode with any ABI-encoded constructor args
  appended. For address parity these bytes must be identical on every chain.
- `abi` - the ABI used to wrap the deployed contract.
- `contract_name` - display name for the wrapped contracts.
- `salt` - an explicit 32-byte salt; defaults to a deterministic salt derived
  from `name`.

Returns a [`Pair`](contract.md) whose members share one `address`.

```python
from statelab.core.build import load_artifact

art = load_artifact(path=FIXTURES, sol_file="HelloWorld.sol", contract_name="HelloWorld")
bytecode = art["bytecode"]["object"]
creation = bytes.fromhex(bytecode[2:] if bytecode.startswith("0x") else bytecode)
pair = lab.create2.deploy_pair("hello", creation, art["abi"], "HelloWorld")
assert pair.on(earth).address == pair.on(mars).address
```

## Invariants

The deployer enforces two requirements and raises if either is broken:

- **Equal deployer nonces.** The shared factory must itself land at the same
  address on every chain, which holds only when the deployers' nonces match at
  deploy time. Deploy bridges and CREATE2 contracts before any asymmetric
  per-chain transactions.
- **Byte-identical creation code.** The address depends on the creation code, so
  constructor arguments must be the same on every chain. The `BridgeableToken`
  plugin holds its peer fields at zero in the constructor and wires the real
  peer afterwards to keep the bytes identical.

## `salt_from_name`

```python
from statelab.core.create2 import salt_from_name
salt_from_name(name) -> bytes      # deterministic 32-byte CREATE2 salt
```

The default salt `deploy_pair` uses when none is given. Exported for plugins
that need to predict or reuse a specific salt.
