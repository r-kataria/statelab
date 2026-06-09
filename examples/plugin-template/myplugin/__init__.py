"""A minimal StateLab plugin.

Copy this directory, rename the `myplugin` package, and swap the contract and
behaviour for your own. The class below touches every hook a plugin can have, so
it doubles as a checklist.
"""
from __future__ import annotations

from statelab import Contract, Plugin
from statelab.core.build import load_artifact


class CounterPlugin(Plugin):
    """Deploys a Counter on one chain and adds a random 1-3 to it each block."""

    def __init__(self, chain, plugin_name: str = "counter"):
        # `name` must be unique within a run. It keys the plugin's RNG and its
        # summary section, so take it as an argument and two instances can coexist.
        self.name = plugin_name
        self.chain = chain
        self.contract = None

    def setup(self, lab):
        # Deploy in setup, not __init__: the chains are not up yet at construction.
        artifact = load_artifact(
            package="myplugin", sol_file="Counter.sol", contract_name="Counter")
        self.contract = Contract.deploy(
            self.chain, artifact, contract_name="Counter",
            from_=self.chain.deployer)

    def on_block(self, ctx):
        # on_block fires every tick; act only when this chain actually mined.
        if self.chain.name not in ctx.mined:
            return
        # Take randomness from ctx.rng (seeded per plugin) so the run replays.
        n = ctx.rng.randint(1, 3)
        # State-changing calls return a PendingTx; .wait() mines and decodes it.
        self.contract.add(n, from_=self.chain.deployer).wait()
        # ctx.record / ctx.emit are the only output path, and they keep determinism.
        ctx.record("count", self.contract.count(), chain=self.chain.name)

    def summary(self):
        # Optional: contributes a section to summary.json, keyed by self.name.
        return {"final_count": int(self.contract.count())}
