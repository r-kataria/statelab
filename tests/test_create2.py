import pytest

from statelab import Lab, Time
from statelab.core.build import load_artifact
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.integration
def test_create2_same_address_across_chains(anvil_pair):
    with Lab(seed=1, duration=Time(1), outdir="out/_create2") as lab:
        earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
        mars = lab.chain("mars", chain_id=31338, blocktime=Time(12))
        art = load_artifact(path=FIXTURES, sol_file="HelloWorld.sol", contract_name="HelloWorld")
        bytecode = art["bytecode"]["object"]
        if bytecode.startswith("0x"):
            bytecode = bytecode[2:]
        creation = bytes.fromhex(bytecode)  # HelloWorld has no ctor args
        pair = lab.create2.deploy_pair("hello", creation, art["abi"], "HelloWorld")
        assert pair.on(earth).address == pair.on(mars).address
        # read state on both chains to confirm the deploy landed on each
        assert pair.on(earth).getValue() == 0
        assert pair.on(mars).getValue() == 0
        lab.run()
