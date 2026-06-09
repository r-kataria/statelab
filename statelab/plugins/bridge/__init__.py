"""Cross-chain bridge with a Python-side relay (StateLab plugin).

Architecture
------------
A ``DtnBridge`` contract is deployed on each side of the pair. The contract
recognises a single payload kind: a low-level call ``(target, value, data)``
to be executed on the destination chain. Token movement is performed by the
token contracts themselves (``BridgeableERC20.bridgeSend`` /
``bridgeMint``); the bridge does not hold or escrow any tokens.

Lifecycle of a message
----------------------
1. **Send.** Caller invokes :meth:`RelayBridge.send_call` (or :meth:`send_raw`).
   This runs ``DtnBridge.send`` on the source chain, which emits a
   ``MessageSent(nonce, sender, target, value, data)`` log.
2. **Queue.** The Python side picks up the log either eagerly (when
   ``send_raw`` returns and stores the message in ``_index``) or lazily via
   :meth:`RelayBridge.poll`. Each queued message gets ``deliver_at = now + delay``.
3. **Deliver.** Once simulated time advances past ``deliver_at``,
   :meth:`RelayBridge.deliver_due` submits ``DtnBridge.deliver(...)`` on the
   destination chain. The on-chain mapping ``delivered[srcNonce]`` makes
   subsequent attempts idempotent.

Relay reliability
-----------------
:class:`RelayBridge` supports a redundant-relay model: up to ``n_relays``
independent processes attempt to land each message; each drops it with
probability ``relay_drop_rate``. Drop decisions are deterministic per
``(src_nonce, relay_idx)`` so a configuration always produces the same
pattern. :meth:`force_deliver` is a self-broadcast escape hatch.

Run model
---------
As a :class:`~statelab.core.plugin.Plugin`, the relay runs block-granular:
``setup`` deploys the ``DtnBridge`` pair, and ``on_block`` runs ``poll`` then
``deliver_due(now)`` once per tick.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Optional

from web3 import Web3

from ...core.build import load_artifact
from ...core.contract import Contract, PendingTx
from ...core.plugin import Plugin
from ...core.time import TimeControl, TimeValue
from ...core.wallet import Wallet

log = logging.getLogger("statelab")

# Address used as ``mintToken=0`` etc. The canonical "no token" sentinel.
_ZERO_ADDRESS = "0x" + "0" * 40


# ====================================================================== #
# Data classes
# ====================================================================== #

@dataclass
class _QueuedMessage:
    """One pending cross-chain message awaiting delivery."""
    src_nonce: int
    src_chain: str
    dst_chain: str
    sender: str
    target: str
    value: int
    data: bytes
    deliver_at: int                        # simulated base units
    src_tx_hash: bytes = b""
    src_block_number: int = -1
    delivered: bool = False
    deliver_tx_hash: bytes = b""
    failed: bool = False
    # Count of full deliver_due passes where every relay dropped this message.
    # Used by tests + telemetry; does not gate retry.
    relay_attempts: int = 0


@dataclass
class PendingBridgeTx:
    """Handle returned by :meth:`RelayBridge.send_call` / :meth:`send_raw`.

    A bridge tx has two phases:

    * The source-side ``send`` (already mined when this handle is returned).
    * The destination-side ``deliver`` (submitted by the relay after the
      delay has elapsed in simulated time). :meth:`wait_delivery` drives the
      simulated clock until that lands.
    """
    bridge: "RelayBridge"
    src_nonce: int
    src_chain_name: str
    dst_chain_name: str
    source_tx: PendingTx
    _msg: _QueuedMessage

    def wait_source(self) -> "PendingBridgeTx":
        """Ensure the source-side tx is included. Already was at construction;
        kept for API symmetry."""
        self.source_tx.wait()
        return self

    @property
    def delivered(self) -> bool:
        return self._msg.delivered

    @property
    def deliver_at(self) -> int:
        return self._msg.deliver_at

    def wait_delivery(self, timeout_blocks: int = 10_000) -> "PendingBridgeTx":
        """Drive simulated time forward until this message lands on the
        destination chain.

        Runs in *simulated* time, not wall-clock. A delay of e.g. 1440 base
        units is 1440 base units regardless of the harness's ``fastforward``
        multiplier.

        Raises if the bound :class:`TimeControl` is missing or frozen, since both
        states would otherwise spin to ``timeout_blocks`` without delivering.
        """
        time_control = self.bridge.time_control
        self._require_advanceable_clock(time_control)
        self.bridge.poll()  # make sure we have seen our own message

        for _step in range(timeout_blocks):
            if self._msg.delivered:
                return self
            self._require_advanceable_clock(time_control)
            self._tick_one_step(time_control)
        raise RuntimeError(
            f"PendingBridgeTx.wait_delivery: not delivered after {timeout_blocks} steps"
        )

    # -- internals ------------------------------------------------------- #

    @staticmethod
    def _require_advanceable_clock(time_control: Optional[TimeControl]) -> None:
        if time_control is None:
            raise RuntimeError(
                "PendingBridgeTx.wait_delivery: bridge has no TimeControl bound; "
                "the RelayBridge plugin binds this from lab.Time in setup()."
            )
        if time_control.is_frozen:
            raise RuntimeError(
                "PendingBridgeTx.wait_delivery: cannot wait while Time is frozen; "
                "call Time.resume() first"
            )

    def _tick_one_step(self, time_control: TimeControl) -> None:
        # Jump to deliver_at if we haven't reached it yet, otherwise nudge by
        # one base unit so simulated time always advances each iteration.
        if time_control.now < self._msg.deliver_at:
            time_control.advance(self._msg.deliver_at - time_control.now)
        # Mine both endpoints so any pending source-side or destination-side
        # txs land before we attempt deliver_due.
        for chain in (self.bridge.a, self.bridge.b):
            try:
                chain.mine(timestamp=time_control.now_wall)
            except Exception:
                chain.mine()
        self.bridge.poll()
        self.bridge.deliver_due(time_control.now)
        if not self._msg.delivered:
            time_control.advance(1)


# ====================================================================== #
# RelayBridge
# ====================================================================== #

class RelayBridge(Plugin):
    """Bidirectional bridge between two chains, as a StateLab plugin.

    ``setup`` deploys a ``DtnBridge`` contract on each chain. The bridge owner
    is the chain deployer; that EOA must be the one that signs ``deliver``
    calls in the relay (the on-chain contract gates ``deliver`` on
    ``onlyOwner``). ``on_block`` polls for new messages and delivers any whose
    delay has elapsed.
    """

    name: str = "bridge"

    def __init__(
        self,
        chain_a: Any,
        chain_b: Any,
        delay: TimeValue,
        n_relays: int = 1,
        relay_drop_rate: float = 0.0,
        relay_seed: int = 0,
        name: str = "bridge",
    ) -> None:
        self._validate_relay_args(n_relays, relay_drop_rate)
        # Endpoints.
        self.a = chain_a
        self.b = chain_b
        self.delay: TimeValue = delay
        self.name = name
        # Relay reliability model.
        self.n_relays: int = int(n_relays)
        self.relay_drop_rate: float = float(relay_drop_rate)
        self.relay_seed: int = int(relay_seed)
        # Owners default to each chain's deployer (set in setup()).
        self._owner_a: Optional[Wallet] = None
        self._owner_b: Optional[Wallet] = None
        # Bridge contracts (deployed in setup()).
        self.bridge_a: Optional[Contract] = None
        self.bridge_b: Optional[Contract] = None
        # Clock (bound from lab.Time in setup()).
        self.time_control: Optional[TimeControl] = None
        # Message queue + (chain, nonce) -> message index.
        self._queue: list[_QueuedMessage] = []
        self._index: dict[tuple[str, int], _QueuedMessage] = {}
        # Incremental scan cursor per chain (highest block already polled).
        self._last_scanned: dict[str, int] = {
            chain_a.name: -1, chain_b.name: -1,
        }

    @staticmethod
    def _validate_relay_args(n_relays: int, relay_drop_rate: float) -> None:
        if n_relays < 1:
            raise ValueError(f"n_relays must be >= 1, got {n_relays}")
        if not (0.0 <= relay_drop_rate <= 1.0):
            raise ValueError(f"relay_drop_rate must be in [0, 1], got {relay_drop_rate}")

    # ------------------------------------------------------------------ #
    # Plugin hooks
    # ------------------------------------------------------------------ #

    def setup(self, lab: Any) -> None:
        """Deploy the ``DtnBridge`` pair and bind the clock.

        ``DtnBridge`` is deployed by a plain ``Contract.deploy`` from each
        chain's deployer (not via the CREATE2 factory) so that ``owner``,
        set to ``msg.sender`` in the constructor, is the deployer, which is
        the EOA that signs ``deliver``. The two contracts must land at the
        same address for the relay's symmetric routing to work; this holds
        when the deployers' nonces are equal at deploy time, so the bridge
        must be registered before any asymmetric per-chain transactions.
        """
        artifact = load_artifact(
            package="statelab.plugins.bridge",
            sol_file="DtnBridge.sol",
            contract_name="DtnBridge",
        )
        self._owner_a = self.a.deployer
        self._owner_b = self.b.deployer
        self.bridge_a = Contract.deploy(
            self.a, artifact, contract_name="DtnBridge", from_=self._owner_a,
        )
        self.bridge_b = Contract.deploy(
            self.b, artifact, contract_name="DtnBridge", from_=self._owner_b,
        )
        if self.bridge_a.address != self.bridge_b.address:
            raise RuntimeError(
                "RelayBridge.setup: DtnBridge addresses differ across chains "
                f"({self.bridge_a.address} on {self.a.name!r} vs "
                f"{self.bridge_b.address} on {self.b.name!r}); cannot achieve "
                "address parity. Deploy the bridge before any asymmetric "
                "per-chain transactions so the deployer nonces match."
            )
        self.time_control = lab.Time

    def on_block(self, ctx: Any) -> None:
        """Per-block relay tick: poll for new messages, deliver any that are due."""
        self.poll()
        delivered = self.deliver_due(ctx.now)
        if delivered:
            ctx.emit({
                "kind": "bridge_deliver",
                "who": f"{self.a.name}<->{self.b.name}",
                "count": delivered,
            })

    def summary(self) -> dict:
        # A `failed` message also has delivered=True (the nonce is burned on
        # chain), so exclude it from the success count and report it separately.
        return {
            "pending": len(self.pending()),
            "delivered": sum(1 for m in self._queue if m.delivered and not m.failed),
            "failed": sum(1 for m in self._queue if m.failed),
        }

    # ------------------------------------------------------------------ #
    # Public API: send
    # ------------------------------------------------------------------ #

    def send_call(
        self,
        target_contract: Contract,
        method_name: str,
        args: list,
        *,
        src: Any = None,
        dst: Any = None,
        from_: Wallet,
        value: int = 0,
    ) -> PendingBridgeTx:
        """Queue a cross-chain contract call.

        ``target_contract`` must already live on ``dst``. The calldata is
        encoded locally; the bridge ships it as opaque bytes.
        """
        src = src or self.a
        dst = dst or self.b
        if target_contract.chain.name != dst.name:
            raise ValueError(
                f"send_call: target_contract is on {target_contract.chain.name!r} "
                f"but dst is {dst.name!r}"
            )
        calldata = _encode_call(target_contract, method_name, args)
        return self.send_raw(
            target_address=target_contract.address,
            data=calldata,
            value=value,
            src=src,
            dst=dst,
            from_=from_,
        )

    def send_raw(
        self,
        *,
        target_address: str,
        data: bytes,
        value: int = 0,
        src: Any = None,
        dst: Any = None,
        from_: Wallet,
    ) -> PendingBridgeTx:
        """Low-level bridge send.

        Use when you already have raw calldata, e.g. for a Router intent or a
        target whose ABI is not wrapped by :class:`Contract`.
        """
        src = src or self.a
        dst = dst or self.b
        bridge_src = self._bridge_on(src)

        tx = bridge_src.send(
            Web3.to_checksum_address(target_address),
            int(value), bytes(data),
            from_=from_, value=int(value),
        )
        tx.wait()
        if tx.status != 1:
            raise RuntimeError(f"RelayBridge.send failed: receipt={tx.receipt}")

        # Extract the MessageSent event so we can index the queued message.
        sent_event = next((e for e in tx.events if e["name"] == "MessageSent"), None)
        if sent_event is None:
            raise RuntimeError("RelayBridge.send_raw: no MessageSent event found")
        message = self._enqueue_from_event(sent_event, tx, src, dst)
        return PendingBridgeTx(
            bridge=self,
            src_nonce=message.src_nonce,
            src_chain_name=src.name,
            dst_chain_name=dst.name,
            source_tx=tx,
            _msg=message,
        )

    def _enqueue_from_event(
        self, event: dict, tx: PendingTx, src: Any, dst: Any,
    ) -> _QueuedMessage:
        """Build a :class:`_QueuedMessage` from a MessageSent event and index it."""
        args = event["args"]
        src_nonce = int(args["nonce"])
        now = self.time_control.now if self.time_control is not None else 0
        message = _QueuedMessage(
            src_nonce=src_nonce,
            src_chain=src.name,
            dst_chain=dst.name,
            sender=args["sender"],
            target=args["target"],
            value=int(args["value"]),
            data=bytes(args["data"]),
            deliver_at=now + int(self.delay),
            src_tx_hash=bytes(tx.tx_hash),
            src_block_number=int(tx.receipt["blockNumber"]),
        )
        self._queue.append(message)
        self._index[(src.name, src_nonce)] = message
        # Bump scan cursor so poll() won't double-record the same message.
        self._last_scanned[src.name] = max(
            self._last_scanned[src.name], message.src_block_number,
        )
        return message

    # ------------------------------------------------------------------ #
    # Public API: relay ticks
    # ------------------------------------------------------------------ #

    def poll(self) -> int:
        """Scan both sides for new MessageSent logs and enqueue them.

        Idempotent: a message already enqueued by :meth:`send_raw` is skipped
        (deduplicated by ``(src_chain, src_nonce)``). Returns the count of
        newly-enqueued messages.
        """
        new_count = 0
        for src_chain, bridge_src, dst_chain in self._direction_pairs():
            new_count += self._poll_direction(src_chain, bridge_src, dst_chain)
        return new_count

    def _direction_pairs(self) -> list[tuple[Any, Contract, Any]]:
        """Yield ``(src_chain, src_bridge, dst_chain)`` for each direction."""
        return [
            (self.a, self.bridge_a, self.b),
            (self.b, self.bridge_b, self.a),
        ]

    def _poll_direction(
        self, src_chain: Any, bridge_src: Contract, dst_chain: Any,
    ) -> int:
        from_block = self._last_scanned[src_chain.name] + 1
        to_block = src_chain.head_number()
        if from_block > to_block:
            return 0
        logs = self._fetch_message_logs(bridge_src, from_block, to_block)
        new_count = 0
        for entry in logs:
            args = entry["args"]
            src_nonce = int(args["nonce"])
            key = (src_chain.name, src_nonce)
            if key in self._index:
                continue  # already enqueued by send_raw
            now = self.time_control.now if self.time_control is not None else 0
            message = _QueuedMessage(
                src_nonce=src_nonce,
                src_chain=src_chain.name,
                dst_chain=dst_chain.name,
                sender=args["sender"],
                target=args["target"],
                value=int(args["value"]),
                data=bytes(args["data"]),
                deliver_at=now + int(self.delay),
                src_block_number=int(entry.get("blockNumber", -1)),
            )
            self._queue.append(message)
            self._index[key] = message
            new_count += 1
        self._last_scanned[src_chain.name] = to_block
        return new_count

    @staticmethod
    def _fetch_message_logs(
        bridge_src: Contract, from_block: int, to_block: int,
    ) -> list:
        """Fetch MessageSent logs across web3.py versions (kw renamed in 7.x)."""
        event = bridge_src.events["MessageSent"]
        try:
            return event.get_logs(from_block=from_block, to_block=to_block)
        except TypeError:
            return event.get_logs(fromBlock=from_block, toBlock=to_block)

    def deliver_due(self, now: int) -> int:
        """Deliver every queued message whose ``deliver_at <= now``.

        Reliability model: for each eligible message, up to :attr:`n_relays`
        independent relays attempt delivery. Each drops with probability
        :attr:`relay_drop_rate` (deterministic per ``(src_nonce, relay_idx)``).
        The first relay that does NOT drop attempts the submission; remaining
        relays no-op once delivered (the on-chain ``delivered`` mapping makes
        this idempotent).

        Returns the number of newly-delivered messages this pass.
        """
        eligible_indices = [
            i for i, msg in enumerate(self._queue)
            if not msg.delivered and msg.deliver_at <= now
        ]
        log.debug(
            "deliver_due START now=%d eligible=%d queue=%d n_relays=%d drop_rate=%.3f",
            now, len(eligible_indices), len(self._queue),
            self.n_relays, self.relay_drop_rate,
        )
        delivered_count = 0
        for queue_idx in eligible_indices:
            if self._attempt_delivery(self._queue[queue_idx], queue_idx):
                delivered_count += 1
        log.debug("deliver_due END delivered=%d", delivered_count)
        return delivered_count

    def _attempt_delivery(self, message: _QueuedMessage, queue_idx: int) -> bool:
        """Run the relay loop for one message. Returns True if it landed (or
        was already delivered) this pass."""
        _src, bridge_dst, owner = self._dst_triple(message.dst_chain)
        all_relays_dropped = True
        for relay_idx in range(self.n_relays):
            if self._relay_drops(message.src_nonce, relay_idx):
                log.debug(
                    "deliver_due[%d] relay=%d DROPPED src_nonce=%d",
                    queue_idx, relay_idx, message.src_nonce,
                )
                continue
            all_relays_dropped = False
            outcome = self._try_one_relay(message, bridge_dst, owner, queue_idx, relay_idx)
            if outcome == "delivered":
                return True
            if outcome == "failed":
                return False
            # "retry" -> next relay
        if all_relays_dropped:
            message.relay_attempts += 1
            log.debug(
                "deliver_due[%d] src_nonce=%d ALL %d relays dropped (attempts=%d)",
                queue_idx, message.src_nonce, self.n_relays, message.relay_attempts,
            )
        return False

    def _try_one_relay(
        self,
        message: _QueuedMessage,
        bridge_dst: Contract,
        owner: Wallet,
        queue_idx: int,
        relay_idx: int,
    ) -> str:
        """Attempt to submit ``message`` via one relay.

        Returns one of:
          * ``"delivered"``: the message landed (or was already on-chain).
          * ``"failed"``: the target-side execution failed in a definitive way.
          * ``"retry"``: submission itself rejected, try the next relay.
        """
        # Idempotency pre-flight: another relay may have landed it already.
        if self._already_delivered_onchain(bridge_dst, message.src_nonce):
            log.debug(
                "deliver_due[%d] relay=%d src_nonce=%d already delivered (idempotency)",
                queue_idx, relay_idx, message.src_nonce,
            )
            message.delivered = True
            return "delivered"

        # Submit.
        try:
            tx = bridge_dst.deliver(
                int(message.src_nonce),
                Web3.to_checksum_address(message.sender),
                Web3.to_checksum_address(message.target),
                int(message.value),
                message.data,
                from_=owner,
            )
            tx.wait()
        except Exception as exc:
            log.debug(
                "deliver_due[%d] relay=%d submission raised: %r",
                queue_idx, relay_idx, exc,
            )
            # Re-check: a competing relay may have landed it between our
            # pre-flight and our submission.
            if self._already_delivered_onchain(bridge_dst, message.src_nonce):
                message.delivered = True
                return "delivered"
            return "retry"

        if tx.status == 1:
            message.delivered = True
            message.deliver_tx_hash = bytes(tx.tx_hash)
            return "delivered"

        # Status 0 (reverted). Distinguish idempotency from genuine target-side
        # revert by re-reading the delivered mapping.
        if self._already_delivered_onchain(bridge_dst, message.src_nonce):
            # Either our own tx flipped the mapping before the inner call
            # reverted, or a competing relay set it. In both cases this nonce
            # can never land again. Mark it failed so callers can tell.
            message.delivered = True
            message.deliver_tx_hash = bytes(tx.tx_hash)
            message.failed = True
            return "failed"
        # Genuine revert; another relay may still succeed.
        log.warning(
            "deliver_due[%d] relay=%d src_nonce=%d reverted but delivered==false; "
            "trying next relay",
            queue_idx, relay_idx, message.src_nonce,
        )
        return "retry"

    @staticmethod
    def _already_delivered_onchain(bridge_dst: Contract, src_nonce: int) -> bool:
        """Read the destination-side ``delivered[srcNonce]`` mapping.

        Tolerates RPC hiccups: any exception here is treated as "unknown",
        which the caller handles as "go ahead and try the submission".
        """
        try:
            return bool(bridge_dst.delivered(int(src_nonce)))
        except Exception:
            return False

    def _relay_drops(self, src_nonce: int, relay_idx: int) -> bool:
        """Deterministic per-``(message, relay)`` drop decision.

        Seeded by ``relay_seed + relay_idx + src_nonce`` so a given config
        always produces the same drop pattern. A fresh :class:`random.Random`
        is built per decision so the result is independent of call order.
        """
        if self.relay_drop_rate <= 0.0:
            return False
        if self.relay_drop_rate >= 1.0:
            return True
        rng = random.Random(self.relay_seed + relay_idx + int(src_nonce))
        return rng.random() < self.relay_drop_rate

    # ------------------------------------------------------------------ #
    # Escape hatch
    # ------------------------------------------------------------------ #

    def force_deliver(
        self,
        src_nonce: int,
        src_chain_name: Optional[str] = None,
        from_: Optional[Wallet] = None,
    ) -> bool:
        """Submit a queued message unconditionally, bypassing relay drops.

        Models the "if all relays die, the bridge owner submits the proof
        themselves" pattern. Returns ``True`` if the message landed (or was
        already delivered), ``False`` if no such message exists in our queue.

        ``from_`` is accepted for API symmetry but ignored. The contract's
        ``deliver`` is ``onlyOwner``, so the bridge owner key is always used.
        """
        del from_  # ignored; see docstring
        message = self._lookup_for_force_deliver(int(src_nonce), src_chain_name)
        if message is None:
            return False
        if message.delivered and not message.failed:
            return True

        _src, bridge_dst, owner = self._dst_triple(message.dst_chain)
        if self._already_delivered_onchain(bridge_dst, message.src_nonce):
            message.delivered = True
            return True

        tx = bridge_dst.deliver(
            int(message.src_nonce),
            Web3.to_checksum_address(message.sender),
            Web3.to_checksum_address(message.target),
            int(message.value),
            message.data,
            from_=owner,
        )
        tx.wait()
        if tx.status == 1:
            message.delivered = True
            message.deliver_tx_hash = bytes(tx.tx_hash)
            return True
        # Reverted, but the on-chain mapping may still have flipped.
        if self._already_delivered_onchain(bridge_dst, message.src_nonce):
            message.delivered = True
            message.deliver_tx_hash = bytes(tx.tx_hash)
            return True
        return False

    def _lookup_for_force_deliver(
        self, src_nonce: int, src_chain_name: Optional[str],
    ) -> Optional[_QueuedMessage]:
        if src_chain_name is not None:
            return self._index.get((src_chain_name, src_nonce))
        # No chain hint -> search both sides (rare; relay code paths always
        # know the chain).
        for (_chain, nonce), message in self._index.items():
            if int(nonce) == src_nonce:
                return message
        return None

    # ------------------------------------------------------------------ #
    # Token convenience (used by the BridgeableToken plugin)
    # ------------------------------------------------------------------ #

    def bridge_token_via(
        self,
        src_token_contract: Contract,
        recipient_addr: str,
        amount: int,
        src_chain: Any,
        from_wallet: Wallet,
    ) -> PendingBridgeTx:
        """Burn ``amount`` on the source token; return a handle for its delivery.

        Runs the token contract's ``bridgeSend`` (which burns and internally
        calls ``DtnBridge.send``), polls the bridge for the new ``MessageSent``
        log, then locates the queued message produced by this tx so the caller
        gets a :class:`PendingBridgeTx`.
        """
        dst_chain = self.b if src_chain.name == self.a.name else self.a

        # Step 1: source-side bridgeSend (burns the tokens, emits MessageSent
        # via the bridge contract).
        send_tx = src_token_contract.bridgeSend(
            Web3.to_checksum_address(recipient_addr), int(amount), from_=from_wallet,
        )
        send_tx.wait()
        if send_tx.status != 1:
            raise RuntimeError(
                f"bridge_token_via: bridgeSend failed: receipt={send_tx.receipt}"
            )

        # Step 2: pick up the new MessageSent log. The log is emitted by the
        # bridge contract (not the token), so poll the bridge directly.
        self.poll()

        # Step 3: locate the queued message this tx produced.
        message = _locate_recent_message(
            self, src_chain, send_tx.receipt["blockNumber"],
        )
        return PendingBridgeTx(
            bridge=self,
            src_nonce=message.src_nonce,
            src_chain_name=src_chain.name,
            dst_chain_name=dst_chain.name,
            source_tx=send_tx,
            _msg=message,
        )

    # ------------------------------------------------------------------ #
    # Accessors
    # ------------------------------------------------------------------ #

    def pending(self) -> list[_QueuedMessage]:
        """All queued messages that have not yet been delivered."""
        return [m for m in self._queue if not m.delivered]

    def address_on(self, chain: Any) -> str:
        """Address of the bridge contract on ``chain``."""
        return self._bridge_on(chain).address

    def bridge_on(self, chain: Any) -> Contract:
        """The :class:`Contract` wrapper for the bridge on ``chain``."""
        return self._bridge_on(chain)

    # -- internals ------------------------------------------------------- #

    def _bridge_on(self, chain: Any) -> Contract:
        if chain.name == self.a.name:
            return self.bridge_a
        if chain.name == self.b.name:
            return self.bridge_b
        raise ValueError(f"chain {chain.name!r} is not part of this bridge")

    def _dst_triple(self, dst_name: str) -> tuple[Any, Contract, Wallet]:
        """Return ``(chain, bridge_contract, owner_wallet)`` for the destination side."""
        if dst_name == self.a.name:
            return self.a, self.bridge_a, self._owner_a
        return self.b, self.bridge_b, self._owner_b

    def __repr__(self) -> str:
        return (
            f"RelayBridge({self.a.name!r} <-> {self.b.name!r}, "
            f"delay={int(self.delay)}, queued={len(self.pending())})"
        )


# ====================================================================== #
# Module-level helpers
# ====================================================================== #

def _encode_call(contract: Contract, method_name: str, args: list) -> bytes:
    """Build raw calldata for ``contract.method_name(*args)`` via the wrapped ABI."""
    fn = getattr(contract._w3_contract.functions, method_name)(*args)
    return bytes.fromhex(fn._encode_transaction_data()[2:])


def _locate_recent_message(bridge: Any, src_chain: Any, src_block_number: int):
    """Pull the queued :class:`_QueuedMessage` that came from ``src_block_number``.

    The bridge's MessageSent log isn't decoded by the token's Contract.events
    (it's emitted by the bridge contract, not the token), so we identify the
    message by the source-side block number that just landed our tx.
    """
    pending = bridge.pending()
    matches = [
        m for m in pending
        if m.src_chain == src_chain.name and m.src_block_number == src_block_number
    ]
    if not matches:
        # Fallback: any pending message on this source chain. Could happen if
        # blockNumber bookkeeping drifts; the typical case is a fresh send.
        matches = [m for m in pending if m.src_chain == src_chain.name]
    if not matches:
        raise RuntimeError("bridge_token_via: could not locate queued MessageSent")
    return matches[-1]
