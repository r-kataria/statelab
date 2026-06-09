"""Offline guard tests for Lab (no chains constructed, no docker needed)."""
import pytest

from statelab import Lab, Plugin, Time


def _lab():
    # auto_docker=False and never entering the context manager keeps this offline.
    return Lab(seed=0, duration=Time(60), outdir="out/_test_guards", auto_docker=False)


def test_use_rejects_duplicate_plugin_names():
    lab = _lab()
    a, b = Plugin(), Plugin()
    a.name = b.name = "dup"
    lab.use(a)
    with pytest.raises(ValueError):
        lab.use(b)


def test_chain_rejects_nonpositive_blocktime():
    # The guard fires before any Chain/RPC construction, so this needs no node.
    lab = _lab()
    with pytest.raises(ValueError):
        lab.chain("earth", chain_id=31337, blocktime=Time(0))
