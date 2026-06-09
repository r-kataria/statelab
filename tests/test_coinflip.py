import hashlib
from pathlib import Path

import pytest

from statelab import Lab, Monitor, RandomTrader, SimpleAMM, Time, Token

WAD = 10**18


def _run(outdir: str) -> bytes:
    with Lab(seed=0xC0FFEE, duration=Time(60 * 30), outdir=outdir) as lab:
        earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
        tx = lab.use(Token("TokenX", "TKX", chain=earth, supply=10**24))
        ty = lab.use(Token("TokenY", "TKY", chain=earth, supply=10**24))
        amm = lab.use(SimpleAMM(earth, tx, ty,
                               initial_liquidity=(1_000 * WAD, 1_000 * WAD)))
        lab.use(Monitor("price", chain=earth, call=amm.get_price))
        for i in range(5):
            lab.use(RandomTrader(f"Actor{i}", amm=amm, token_x=tx, token_y=ty,
                                 chain=earth, min_size=WAD, max_size=50 * WAD,
                                 fund_each=1_000 * WAD))
        lab.run()
    return (Path(outdir) / "monitors.csv").read_bytes()


@pytest.mark.integration
def test_coinflip_runs_and_moves_price(tmp_path, anvil_pair):
    data = _run(str(tmp_path / "run1"))
    text = data.decode()
    assert "price" in text
    # the price series must contain more than one distinct value (trades moved it)
    import csv, io
    rows = list(csv.DictReader(io.StringIO(text)))
    prices = {r["value"] for r in rows if r["name"] == "price"}
    assert len(prices) > 1


@pytest.mark.integration
def test_coinflip_bit_identical(tmp_path, anvil_pair):
    a = _run(str(tmp_path / "a"))
    b = _run(str(tmp_path / "b"))
    assert hashlib.md5(a).hexdigest() == hashlib.md5(b).hexdigest()
