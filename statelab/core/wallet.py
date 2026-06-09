"""Wallets are thin wrappers around an ``eth_account`` account plus a reference
to the home chain. Keys are derived deterministically from the Anvil dev
mnemonic, so the same account index always resolves to the same key."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from eth_account import Account

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .chain import Chain

# Anvil's default dev mnemonic. Matches docker-compose.
DEFAULT_MNEMONIC = "test test test test test test test test test test test junk"
DEFAULT_DERIVATION = "m/44'/60'/0'/0/{i}"

# Enable HD-account features in eth-account (Account.from_mnemonic is opt-in).
Account.enable_unaudited_hdwallet_features()


@dataclass
class Wallet:
    """A funded EOA on a specific chain."""
    name: str
    chain: "Chain"
    account: Account

    @property
    def address(self) -> str:
        return self.account.address

    @property
    def key(self) -> str:
        return self.account.key.hex()

    # ---- balance helpers ----------------------------------------------------

    def native_balance(self) -> int:
        return self.chain.w3.eth.get_balance(self.address)

    def __repr__(self) -> str:
        return f"Wallet(name={self.name!r}, address={self.address}, chain={self.chain.name!r})"


def derive_account(index: int, mnemonic: str = DEFAULT_MNEMONIC) -> Account:
    """Derive the ``index``th account from a BIP-44 mnemonic."""
    path = DEFAULT_DERIVATION.format(i=index)
    return Account.from_mnemonic(mnemonic, account_path=path)
