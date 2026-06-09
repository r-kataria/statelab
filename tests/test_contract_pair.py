import pytest

from statelab.core.contract import Pair


class _FakeContract:
    def __init__(self, address, chain_name):
        self.address = address
        class _C:  # minimal chain stand-in
            name = chain_name
        self.chain = _C()


def test_pair_requires_shared_address():
    a = _FakeContract("0x" + "1" * 40, "earth")
    b = _FakeContract("0x" + "2" * 40, "mars")
    with pytest.raises(ValueError):
        Pair("tok", {"earth": a, "mars": b})


def test_pair_accessors():
    addr = "0x" + "1" * 40
    a = _FakeContract(addr, "earth")
    b = _FakeContract(addr, "mars")
    pair = Pair("tok", {"earth": a, "mars": b})
    assert pair.address == addr
    assert pair.earth is a and pair.mars is b
