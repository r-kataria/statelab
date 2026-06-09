"""Redundancy + idempotency test for the RelayBridge relay model.

Ported from the pre-StateLab ``test_bridge_redundancy.py`` (old ``Bridge`` /
``Sim`` API). The reliability properties under test are unchanged:

  * ``RelayBridge(n_relays=N, relay_drop_rate=p)`` honours the compound drop
    model: a message lands when at least one of ``N`` independent relays does
    not drop it. Expected delivery fraction is ``1 - p ** N``.
  * The destination contract's ``delivered[srcNonce]`` mapping makes duplicate
    submissions a no-op (idempotency). Relays run serialised in one process,
    so the pre-flight ``delivered(...)`` check inside ``deliver_due`` is what
    makes "first non-dropping relay wins, remaining relays no-op" work.
  * ``RelayBridge.force_deliver(src_nonce)`` is a self-broadcast escape hatch
    that bypasses the relay drop probability - every undelivered message can be
    flushed by the bridge owner directly.

Adaptation notes (old API -> StateLab):

  * ``Bridge(... time_control=tc)`` becomes a ``RelayBridge`` plugin registered
    on a ``Lab``; the plugin binds its clock from ``lab.Time`` in ``setup``. The
    old ``_fresh_chains`` helper (manual ``TimeControl`` + ``Chain`` +
    ``anvil_reset``) becomes a fresh ``Lab`` per scenario. ``lab.chain`` already
    resets each Anvil node, so bridge nonces restart at 0 and the deterministic
    ``relay_seed`` reproduces the same per-message drop pattern.
  * No ``lab.run()`` here: the test needs exactly one ``deliver_due`` pass after
    advancing simulated time past every message's ``deliver_at`` and mining a
    block on both endpoints, otherwise the drop-fraction assertions stop being
    deterministic. The bridge pair is deployed by calling the plugin's ``setup``
    directly, the HelloWorld target is deployed on mars afterwards (so the
    bridge keeps its address parity), then ``lab.Time`` and the plugin's
    ``poll`` / ``deliver_due`` / ``force_deliver`` are driven by hand.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from statelab import Lab, RelayBridge, Time
from statelab.core.build import load_artifact
from statelab.core.contract import Contract

FIXTURES = Path(__file__).parent / "fixtures"

# Per-scenario message count. Kept small because each message round-trips two
# Anvil chains and a delay-window mine.
N_MSGS = 10
# Tolerance for the empirical-vs-expected delivered fraction. The CLT band for
# ``Binomial(10, 0.5)`` straddles ~32%-68%, so we accept any run whose mean is
# within +/-5 messages of the expected count. The point of the test is to lock
# in the *direction* (N=3 should beat N=1) and the determinism, not to be a
# statistical sanity check on the RNG.
SLACK_MSGS = 5

DELAY = Time(60)


def _deploy_target_on_mars(mars) -> Contract:
    """Deploy a fresh HelloWorld on mars to act as the cross-chain call target."""
    art = load_artifact(path=FIXTURES, sol_file="HelloWorld.sol",
                        contract_name="HelloWorld")
    return Contract.deploy(mars, art, contract_name="HelloWorld")


def _send_and_drive(bridge, target_on_mars, earth, mars, lab, n_msgs):
    """Submit ``n_msgs`` cross-chain calls and drive the simulator until every
    message has had exactly one chance to be delivered. Returns the list of
    queued ``_QueuedMessage`` objects (one per send).

    Mirrors the original helper: send, advance simulated time past every
    message's ``deliver_at``, mine both endpoints, poll, then one ``deliver_due``.
    """
    alice = earth.wallet("alice", funded_native=10 ** 18)
    msgs = []
    for i in range(n_msgs):
        # Distinct setValue arg per message so we can sanity-check landings.
        pbtx = bridge.send_call(
            target_on_mars, "setValue", [1_000 + i],
            src=earth, dst=mars, from_=alice,
        )
        msgs.append(pbtx._msg)
    # Advance simulated time past every message's deliver_at.
    max_deliver_at = max(m.deliver_at for m in msgs)
    if lab.Time.now < max_deliver_at:
        lab.Time.advance(max_deliver_at - lab.Time.now)
    # Mine a block on each chain so the scan cursor catches up and the
    # destination chain has a fresh head to submit ``deliver`` against.
    for ch in (earth, mars):
        try:
            ch.mine(timestamp=lab.Time.now_wall)
        except Exception:
            ch.mine()
    bridge.poll()
    bridge.deliver_due(lab.Time.now)
    return msgs


def _delivered_count(msgs) -> int:
    return sum(1 for m in msgs if m.delivered and not m.failed)


def _scenario(seed_outdir, n_relays, relay_drop_rate, relay_seed):
    """Build a fresh Lab + RelayBridge (setup only, no run loop), deploy the
    target on mars, drive N_MSGS sends through one deliver_due pass.

    Returns ``(bridge, target, msgs, lab)`` so callers can run force_deliver
    follow-ups against the same live bridge.
    """
    lab = Lab(seed=1, duration=Time(1), outdir=seed_outdir)
    lab.__enter__()
    earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
    mars = lab.chain("mars", chain_id=31338, blocktime=Time(12))
    bridge = lab.use(RelayBridge(
        earth, mars, delay=DELAY,
        n_relays=n_relays, relay_drop_rate=relay_drop_rate, relay_seed=relay_seed,
    ))
    # Deploy the bridge pair (binds the clock from lab.Time). Done before the
    # target deploy so the bridge keeps deployer-nonce address parity.
    bridge.setup(lab)
    # bridge is driven by hand, not lab.run(); mark the lab as already-run so
    # __exit__ only writes outputs (otherwise it calls run(), re-deploying the
    # bridge and breaking nonce parity).
    lab._has_run = True
    target = _deploy_target_on_mars(mars)
    msgs = _send_and_drive(bridge, target, earth, mars, lab, N_MSGS)
    return bridge, target, msgs, lab


@pytest.mark.integration
def test_redundancy_and_force_deliver(anvil_pair):
    # -- Scenario A: N=3, p=0.5 -> expected delivery fraction 1 - 0.5**3 = 87.5%
    br_3, _hello_3, msgs_3, lab_3 = _scenario(
        "out/_redundancy_n3", n_relays=3, relay_drop_rate=0.5, relay_seed=42)
    try:
        delivered_3 = _delivered_count(msgs_3)
        expected_3 = N_MSGS * (1 - 0.5 ** 3)  # = 8.75 for N_MSGS=10
        assert abs(delivered_3 - expected_3) <= SLACK_MSGS, (
            f"N=3 p=0.5: delivered {delivered_3}/{N_MSGS}, "
            f"expected ~{expected_3:.2f} (+/-{SLACK_MSGS})"
        )
        assert 0 < delivered_3 <= N_MSGS, (
            f"N=3 p=0.5: degenerate result {delivered_3}/{N_MSGS}"
        )
    finally:
        lab_3.__exit__(None, None, None)

    # -- Scenario B: N=1, p=0.5 -> expected delivery fraction 50%
    br_1, hello_1, msgs_1, lab_1 = _scenario(
        "out/_redundancy_n1", n_relays=1, relay_drop_rate=0.5, relay_seed=42)
    try:
        delivered_1 = _delivered_count(msgs_1)
        expected_1 = N_MSGS * (1 - 0.5)
        assert abs(delivered_1 - expected_1) <= SLACK_MSGS, (
            f"N=1 p=0.5: delivered {delivered_1}/{N_MSGS}, "
            f"expected ~{expected_1:.2f} (+/-{SLACK_MSGS})"
        )
        # Directional sanity: more relays should land at least as many messages.
        assert delivered_3 >= delivered_1, (
            f"redundancy should not hurt: N=3 delivered {delivered_3}, "
            f"N=1 delivered {delivered_1}"
        )

        # -- Scenario C: force_deliver flushes every undelivered message.
        undelivered_before = [m for m in msgs_1 if not m.delivered]
        for m in undelivered_before:
            ok = br_1.force_deliver(m.src_nonce, src_chain_name=m.src_chain)
            assert ok, f"force_deliver returned False for src_nonce={m.src_nonce}"
        delivered_final = _delivered_count(msgs_1)
        assert delivered_final == N_MSGS, (
            f"after force_deliver: {delivered_final}/{N_MSGS} delivered; "
            f"still pending: {[m.src_nonce for m in msgs_1 if not m.delivered]}"
        )

        # -- Sanity: the destination state reflects at least one landing.
        final_value = hello_1.getValue()
        assert final_value >= 1_000, (
            f"target contract value should be >= 1000 after any landing, "
            f"got {final_value}"
        )
    finally:
        lab_1.__exit__(None, None, None)
