from pathlib import Path

import pytest

from statelab.core.build import load_artifact

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_artifact_from_path_returns_abi_and_bytecode():
    art = load_artifact(path=FIXTURES, sol_file="HelloWorld.sol",
                        contract_name="HelloWorld")
    assert isinstance(art["abi"], list)
    assert any(e.get("name") == "getValue" for e in art["abi"])
    bytecode = art["bytecode"]
    obj = bytecode["object"] if isinstance(bytecode, dict) else bytecode
    assert obj.startswith("0x") and len(obj) > 4


def test_load_artifact_from_package_reads_core_factory():
    art = load_artifact(package="statelab.contracts",
                        sol_file="BridgeableERC20Factory.sol",
                        contract_name="BridgeableERC20Factory")
    assert isinstance(art["abi"], list)


@pytest.mark.parametrize("kwargs", [
    {},                                  # neither package nor path
    {"package": "statelab.contracts", "path": FIXTURES},  # both
])
def test_load_artifact_requires_exactly_one_source(kwargs):
    with pytest.raises(ValueError):
        load_artifact(sol_file="HelloWorld.sol", contract_name="HelloWorld", **kwargs)
