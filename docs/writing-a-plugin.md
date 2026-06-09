# Writing a plugin

A plugin bundles four things: Solidity contracts, their compiled artifacts,
Python bindings that deploy and call those contracts, and behaviour expressed
through the `setup` / `on_block` / `summary` hooks. This page builds one from
scratch and then shows how to ship it as a separate pip package.

## Anatomy of a plugin

A plugin is a Python package directory that carries its own contracts and
artifacts:

```
myplugin/
  __init__.py                 the Plugin subclass and any bindings
  contracts/
    Counter.sol               the Solidity source
  artifacts/
    Counter.sol/
      Counter.json            the compiled artifact: { "abi": [...], "bytecode": ... }
```

The contract source lives under `contracts/`; the compiled artifact lives under
`artifacts/<File.sol>/<ContractName>.json`. The artifact is what ships and what
runs. Foundry is used in development to regenerate it, never at runtime, so a
user of your plugin needs no Solidity toolchain. The layout mirrors Foundry's
own `out/` directory, so `forge build` followed by copying `out/Counter.sol`
into `artifacts/` produces the right structure.

## The artifact

An artifact is a JSON object with an `abi` array and a `bytecode` field (either
a hex string or an object with an `object` key holding the hex). StateLab loads
it by package and file name:

```python
from statelab.core.build import load_artifact

artifact = load_artifact(
    package="myplugin",          # the Python package that ships the artifact
    sol_file="Counter.sol",
    contract_name="Counter",
)
```

`load_artifact` resolves the file through `importlib.resources`, so it works
whether the package is installed normally or in editable mode. (Pass `path=` instead
of `package=` to load from a filesystem directory, as the tests do for fixtures.)

## A minimal worked example

The contract is a per-chain counter:

```solidity
// contracts/Counter.sol
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract Counter {
    uint256 public count;
    function add(uint256 n) external { count += n; }
}
```

The plugin deploys it on a chain in `setup`, adds a random 1-3 to it once per
block in `on_block`, and reports the final count in `summary`:

```python
# __init__.py
from statelab import Contract, Plugin
from statelab.core.build import load_artifact


class CounterPlugin(Plugin):
    def __init__(self, chain, plugin_name="counter"):
        self.name = plugin_name
        self.chain = chain
        self.contract = None

    def setup(self, lab):
        artifact = load_artifact(
            package="myplugin", sol_file="Counter.sol", contract_name="Counter")
        self.contract = Contract.deploy(
            self.chain, artifact, contract_name="Counter",
            from_=self.chain.deployer)

    def on_block(self, ctx):
        if self.chain.name not in ctx.mined:
            return
        n = ctx.rng.randint(1, 3)
        self.contract.add(n, from_=self.chain.deployer).wait()
        ctx.record("count", self.contract.count(), chain=self.chain.name)

    def summary(self):
        return {"final_count": int(self.contract.count())}
```

A few patterns to note, all of which the bundled plugins follow:

- **`name` is mandatory and unique.** It keys the plugin's RNG and its summary
  section, and `lab.use` rejects a duplicate. Take it as a constructor argument
  so two instances of the same plugin can coexist in one run.
- **Deploy in `setup`, not the constructor.** The chains may not be ready when
  the plugin object is built; `setup` runs once the lab is up.
- **Guard `on_block` on `ctx.mined`.** `on_block` fires every tick, but a chain
  only mines when its block time elapses. Acting only when your chain is in
  `ctx.mined` gives "once per block" semantics; acting unconditionally gives
  "every tick".
- **State-changing calls return a `PendingTx`; call `.wait()`.** `add(n, from_=...)`
  submits the transaction and returns a handle; `.wait()` mines until it lands
  and decodes the result. View and pure calls (`count()`) return the value
  directly. A state-changing call without `from_=` raises.
- **Take randomness from `ctx.rng`.** The `randint(1, 3)` draw uses the
  plugin-scoped RNG seeded from `(seed, name)`, so the run replays identically.
  A module-level `random` or the system clock would break that.
- **Use `ctx.record` / `ctx.emit`, not direct file writes.** They are the only
  output path and they preserve determinism.

Register it like any bundled plugin:

```python
from statelab import Lab, Time
from myplugin import CounterPlugin

with Lab(seed=1, duration=Time(60), outdir="out/counter") as lab:
    earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
    lab.use(CounterPlugin(earth))
```

## Determinism in a plugin

To keep a plugin reproducible, take any randomness from `ctx.rng` rather than a
module-level `random` or the system clock, and keep the order in which you submit
transactions in `setup` fixed. `ctx.rng` is seeded from `(lab.seed, self.name)`,
so two plugins with different names never share a sequence, and the same
configuration always replays the same draws. The `RandomTrader` plugin is the
reference example: it draws its direction and size from `ctx.rng` and so
produces an identical trade sequence for a given seed.

## Shipping a plugin as a separate package

A plugin does not need to live inside StateLab. A third party ships one as its
own pip package that depends on `statelab`, imports it, and subclasses `Plugin`,
with nothing in the StateLab core touched. The lane-options plugin is exactly
this: a separate top-level package.

The quickest way to start is to copy
[`examples/plugin-template/`](../examples/plugin-template/) and rename it: it is a
working version of everything below, already wired up with a contract, an
artifact, a `pyproject.toml`, and a test.

A minimal external package:

```
mybridge-plugin/
  pyproject.toml
  mybridge/
    __init__.py               class MyBridge(Plugin): ...
    contracts/
      MyBridge.sol
    artifacts/
      MyBridge.sol/MyBridge.json
```

The `pyproject.toml` declares the dependency on `statelab` and ships the
contracts and artifacts as package data so they travel in the wheel:

```toml
[project]
name = "mybridge-plugin"
dependencies = ["statelab"]

[tool.setuptools.package-data]
mybridge = ["contracts/*.sol", "artifacts/**/*.json"]
```

The binding loads its own artifacts with `package="mybridge"`, the same call the
worked example uses; the package name you pass to `load_artifact` is just your
own. Once installed, a user writes `from mybridge import MyBridge` and
`lab.use(MyBridge(...))` exactly as for a bundled plugin. A `ZkBridge`, a
different AMM, or anything else slots in the same way, and the core never has to
know about it.
