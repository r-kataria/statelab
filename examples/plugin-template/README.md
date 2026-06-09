# StateLab plugin template

A minimal, working StateLab plugin you can copy and make your own. It deploys an
example `Counter` contract on one chain and adds a random number to it each
block. That is enough to exercise every hook (`setup`, `on_block`, `summary`),
the artifact layout, and the determinism pattern, so you can delete the example
and keep the shape.

```
plugin-template/
  pyproject.toml                 name + the dependency on statelab
  foundry.toml                   so `forge build` finds the contract
  myplugin/
    __init__.py                  the Plugin subclass
    contracts/Counter.sol        the example contract (replace it)
    artifacts/Counter.sol/       the compiled artifact (ships in the wheel)
  tests/test_myplugin.py         runs it against a live node
```

## Make it yours

1. Copy this directory out of the StateLab repo and rename it.
2. Rename the `myplugin/` package and the `name` in `pyproject.toml`.
3. Replace `myplugin/contracts/Counter.sol` with your contract and rebuild the
   artifact (below).
4. Rewrite the `CounterPlugin` class for your contract and behaviour.

## Build and run

```bash
anvil --no-mining --chain-id 31337 --port 8545 &   # the supported path; or use Docker
pip install -e .          # pulls in statelab
python -m pytest          # runs the plugin against the live Anvil node
```

`load_artifact(package="myplugin", ...)` finds the compiled JSON inside the
package, so anyone who installs your plugin needs no Solidity toolchain. Foundry
is only for regenerating the artifact when you change the contract:

```bash
forge build
cp -R out/Counter.sol myplugin/artifacts/
```

The `artifacts/` layout mirrors Foundry's `out/`, so that copy is the whole
build step.

## Use it

```python
from statelab import Lab, Time
from myplugin import CounterPlugin

with Lab(seed=1, duration=Time(60), outdir="out/counter") as lab:
    earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
    lab.use(CounterPlugin(earth))
```

See [../../docs/writing-a-plugin.md](../../docs/writing-a-plugin.md) for the full
walk-through of the patterns this template follows.
