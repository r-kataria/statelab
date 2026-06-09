import pytest

from statelab import Actor, Lab, SimpleAMM, Time, Token

WAD = 10**18


@pytest.mark.integration
def test_amm_swap_moves_price(anvil_pair):
    with Lab(seed=3, duration=Time(1), outdir="out/_amm") as lab:
        earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
        tx = lab.use(Token("TokenX", "TKX", chain=earth, supply=1_000_000 * WAD))
        ty = lab.use(Token("TokenY", "TKY", chain=earth, supply=1_000_000 * WAD))
        amm = lab.use(SimpleAMM(earth, tx, ty,
                               initial_liquidity=(1_000 * WAD, 1_000 * WAD)))
        lab.run()
    # 1:1 reserves => price 1 WAD before any swap
    assert amm.get_price() == WAD
    # a trader swaps X->Y; price (Y per X) must fall
    trader = Actor(name="t", chains=[earth])
    earth.set_balance(trader.address, WAD)
    tx.contract.transfer(trader.address, 100 * WAD, from_=earth.deployer).wait()
    tx.contract.approve(amm.contract.address, 2**256 - 1, from_=trader.wallet_on(earth)).wait()
    amm.swap(trader, tx, 100 * WAD).wait()
    assert amm.get_price() < WAD
