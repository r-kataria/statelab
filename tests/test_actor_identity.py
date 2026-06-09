from statelab.core.actor import Actor


class _FakeChain:
    def __init__(self, name):
        self.name = name


def test_actor_address_is_deterministic_for_name():
    c = _FakeChain("earth")
    a = Actor(name="alice", chains=[c])
    b = Actor(name="alice", chains=[c])
    assert a.address == b.address


def test_distinct_names_distinct_addresses():
    c = _FakeChain("earth")
    assert Actor(name="alice", chains=[c]).address != Actor(name="bob", chains=[c]).address


def test_empty_chains_rejected():
    import pytest
    with pytest.raises(ValueError):
        Actor(name="alice", chains=[])


def test_anagram_names_do_not_collide():
    # A naive byte-sum index would map these to the same HD account (and thus
    # the same address/key); the sha256-based index must keep them distinct.
    c = _FakeChain("earth")
    assert Actor(name="ab", chains=[c]).address != Actor(name="ba", chains=[c]).address
    assert Actor(name="alice", chains=[c]).address != Actor(name="ileac", chains=[c]).address
