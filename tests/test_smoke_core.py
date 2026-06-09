import hashlib
from pathlib import Path

import pytest

from statelab import Actor, Contract, Lab, Plugin, Time
from statelab.core.build import load_artifact

FIXTURES = Path(__file__).parent / "fixtures"


class HelloPlugin(Plugin):
    """Deploys HelloWorld on mars in setup; an actor bumps it; records it per block."""
    name = "hello"

    def __init__(self):
        self.contract = None
        self.actor = None
        self._n = 0

    def setup(self, lab):
        mars = lab._chains_by_name["mars"]
        art = load_artifact(path=FIXTURES, sol_file="HelloWorld.sol",
                            contract_name="HelloWorld")
        self.contract = Contract.deploy(mars, art, contract_name="HelloWorld")
        self.actor = Actor(name="alice", chains=[mars])
        self.actor.fund(native=10**18, chain=mars)

    def on_block(self, ctx):
        if "mars" not in ctx.mined:
            return
        self._n += 1
        # deterministic write driven by block count
        self.actor.call(self.contract, "setValue", self._n * 10,
                        chain=ctx.lab._chains_by_name["mars"]).wait()
        ctx.record("value", self.contract.getValue(), chain="mars")

    def summary(self):
        return {"blocks_seen": self._n}


def _run(outdir: str) -> bytes:
    with Lab(seed=42, duration=Time(60), outdir=outdir) as lab:
        lab.chain("earth", chain_id=31337, blocktime=Time(12))
        lab.chain("mars", chain_id=31338, blocktime=Time(12))
        lab.use(HelloPlugin())
    return (Path(outdir) / "monitors.csv").read_bytes()


@pytest.mark.integration
def test_smoke_runs_and_records(tmp_path, anvil_pair):
    data = _run(str(tmp_path / "run1"))
    assert b"value" in data
    assert (tmp_path / "run1" / "events.csv").exists()
    assert (tmp_path / "run1" / "summary.json").exists()


@pytest.mark.integration
def test_determinism_bit_identical(tmp_path, anvil_pair):
    a = _run(str(tmp_path / "a"))
    b = _run(str(tmp_path / "b"))
    assert hashlib.md5(a).hexdigest() == hashlib.md5(b).hexdigest()
