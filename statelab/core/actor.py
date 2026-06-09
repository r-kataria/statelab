"""Actor: a primitive, one EOA operating on one or more chains.

An actor holds a single key (deterministically derived from ``(mnemonic, name)``)
and a :class:`Wallet` per chain at the same address. It can fund itself with
native balance and submit local state-modifying calls. Cross-chain behavior and
scheduling are provided by plugins, not by the primitive.
"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Optional

from .contract import Pair, PendingTx
from .wallet import DEFAULT_MNEMONIC, Wallet, derive_account

if TYPE_CHECKING:  # pragma: no cover
    from .chain import Chain

# Actor accounts start at index 100 so they cannot collide with Anvil's
# pre-funded set (0..9).
_ACTOR_INDEX_BASE = 100


def _name_to_account_index(name: str) -> int:
    # Hash the name (not a byte-sum) so anagrams and unrelated names don't
    # collide onto the same HD index and silently share a key. Mirrors the
    # derivation used by make_plugin_rng.
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return _ACTOR_INDEX_BASE + (int.from_bytes(digest[:4], "big") % 10_000)


class Actor:
    def __init__(
        self,
        *,
        name: str,
        chains: list["Chain"],
        mnemonic: str = DEFAULT_MNEMONIC,
        account_index: Optional[int] = None,
    ) -> None:
        if not chains:
            raise ValueError("Actor: chains= must be non-empty")
        idx = account_index if account_index is not None else _name_to_account_index(name)
        self.name = name
        self._account = derive_account(idx, mnemonic)
        self._chains: list["Chain"] = list(chains)
        self._wallets: dict[str, Wallet] = {
            c.name: Wallet(name=name, chain=c, account=self._account) for c in self._chains
        }

    @property
    def address(self) -> str:
        return self._account.address

    @property
    def chains(self) -> list["Chain"]:
        return list(self._chains)

    def wallet_on(self, chain: "Chain") -> Wallet:
        wallet = self._wallets.get(chain.name)
        if wallet is None:
            wallet = Wallet(name=self.name, chain=chain, account=self._account)
            self._wallets[chain.name] = wallet
            self._chains.append(chain)
        return wallet

    def fund(self, *, native: int, chain: "Chain") -> None:
        """Top the actor's native balance up to ``native`` on ``chain``."""
        wallet = self.wallet_on(chain)
        current = wallet.native_balance()
        if current < native:
            chain.set_balance(wallet.address, native)

    def call(
        self,
        contract: Any,
        method: str,
        *args: Any,
        chain: Optional["Chain"] = None,
        value: int = 0,
        gas: int = 2_000_000,
    ) -> PendingTx:
        """Submit a state-modifying call signed by this actor's wallet."""
        if isinstance(contract, Pair):
            if chain is None:
                raise ValueError("Actor.call: Pair target requires chain=...")
            target = contract.on(chain)
        else:
            target = contract
        target_chain = chain or target.chain
        wallet = self.wallet_on(target_chain)
        fn = getattr(target, method)
        return fn(*args, from_=wallet, value=value, gas=gas)

    def __repr__(self) -> str:
        names = ",".join(c.name for c in self._chains)
        return f"Actor(name={self.name!r}, chains=[{names}], addr={self.address})"
