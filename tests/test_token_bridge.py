"""Cross-chain token-bridge integration test.

Proves the burn-on-source -> relay -> mint-on-destination round trip across
block-granular delivery: a ``BridgeableToken`` is deployed at a parity address
on both chains, the deployer's supply on earth is handed to alice, alice's
balance is bridged to mars, and after the relay delay has elapsed (driven by
the Lab run loop) alice holds the tokens on mars.
"""
import pytest

from statelab import Actor, BridgeableToken, Lab, Plugin, RelayBridge, Time

WAD = 10 ** 18


class Mover(Plugin):
    """One-shot driver: on the first earth block, move 100 TKX from the earth
    deployer to alice and bridge it to mars."""

    name = "mover"

    def __init__(self, token):
        self.token = token
        self.alice = None
        self._done = False

    def setup(self, lab):
        self.alice = Actor(name="alice", chains=lab.chains)
        for c in lab.chains:
            self.alice.fund(native=WAD, chain=c)

    def on_block(self, ctx):
        if self._done or "earth" not in ctx.mined:
            return
        lab = ctx.lab
        earth = lab._chains_by_name["earth"]
        mars = lab._chains_by_name["mars"]
        # The deployer holds the supply on earth; hand 100 TKX to alice, then
        # bridge it to mars (burn on earth, relay, mint on mars).
        self.token.on(earth).transfer(
            self.alice.address, 100 * WAD, from_=earth.deployer
        ).wait()
        self.token.bridge_token(self.alice, 100 * WAD, to_chain=mars, src_chain=earth)
        self._done = True


@pytest.mark.integration
def test_bridge_token_earth_to_mars(anvil_pair):
    with Lab(seed=7, duration=Time(60 * 60), outdir="out/_tokenbridge") as lab:
        earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
        mars = lab.chain("mars", chain_id=31338, blocktime=Time(12))
        bridge = lab.use(RelayBridge(earth, mars, delay=Time(24)))
        tokenX = lab.use(
            BridgeableToken("TokenX", "TKX", bridge=bridge, supply_per_chain=1000 * WAD)
        )
        mover = lab.use(Mover(tokenX))
        lab.run()
    # After the relay delivers (delay 24s, blocktime 12s, duration 1h), alice
    # holds 100 TKX on mars (minted on the destination side).
    assert tokenX.balance_of(mover.alice, mars) == 100 * WAD
    # The Lab swallows on_block exceptions into plugin_error events; assert none
    # fired so a mid-run failure surfaces clearly rather than as a 0 balance.
    assert [e for e in lab._events if e.get("kind") == "plugin_error"] == []
