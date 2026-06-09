"""Runs the plugin against a live Anvil node. Needs an Anvil on 8545: either a
native `anvil --no-mining --chain-id 31337 --port 8545` (the supported path) or
the bundled Docker node, the same as any StateLab run."""
from statelab import Lab, Time

from myplugin import CounterPlugin


def _run():
    with Lab(seed=7, duration=Time(60), outdir="out/counter") as lab:
        earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
        counter = lab.use(CounterPlugin(earth))
        lab.run()
    return counter.summary()["final_count"]


def test_counter_runs():
    assert _run() > 0


def test_counter_is_deterministic():
    # Same seed, same count: the plugin draws only from ctx.rng.
    assert _run() == _run()
